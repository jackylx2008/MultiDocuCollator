from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from multidocu_collator.modules.docx_parser import parse_docx
from multidocu_collator.modules.document_generator import generate_contact_docx
from multidocu_collator.modules.desktop import open_directory, resolve_relative_directory
from multidocu_collator.modules.pdf_exporter import export_pdf_with_word
from multidocu_collator.context import AppContext
from multidocu_collator.flows.create_record_flow import (
    _validated_payload,
    create_record,
    next_sequence,
)
from multidocu_collator.flows.summary_server_flow import _handler_class
from multidocu_collator.config_loader import expand_env, select_cloudstation_root
from multidocu_collator.modules.repository import build_dataset
from multidocu_collator.modules.scanner import scan_data_root
from multidocu_collator.modules.summary_html import build_summary_view, export_summary_html
from multidocu_collator.modules.validation import validate_dataset, validate_summary_html


DOCUMENT_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>需求工作联系单 资料编号 </w:t></w:r><w:r><w:t>给排水-003</w:t></w:r><w:r><w:t> 工程名称 示例工程 日 期 2026年8月9日</w:t></w:r></w:p>
    <w:p><w:r><w:t>致(单位)：示例单位 事由：</w:t></w:r><w:r><w:t>关于测试的事宜</w:t></w:r></w:p>
    <w:p><w:r><w:t>内容：</w:t></w:r><w:del><w:r><w:delText>已删除旧内容</w:delText></w:r></w:del><w:ins><w:r><w:rPr><w:u w:val="single"/></w:rPr><w:t>当前需求第一段</w:t></w:r></w:ins></w:p>
    <w:p><w:r><w:rPr><w:u w:val="single"/></w:rPr><w:t>当前需求第二段</w:t></w:r><w:r><w:t>非下划线说明</w:t></w:r></w:p>
    <w:p><w:r><w:t>备注：</w:t></w:r><w:r><w:rPr><w:u w:val="single"/></w:rPr><w:t>不应进入需求内容</w:t></w:r></w:p>
  </w:body>
</w:document>'''


def make_docx(path: Path) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", DOCUMENT_XML)


TEMPLATE_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>资料编号</w:t></w:r></w:p><w:p><w:r><w:t>消防水-004</w:t></w:r></w:p>
<w:p><w:r><w:t>工程名称</w:t></w:r></w:p><w:p><w:r><w:t>固定工程</w:t></w:r></w:p>
<w:p><w:r><w:t>日   期</w:t></w:r></w:p><w:p><w:r><w:t>2026年8月16日</w:t></w:r></w:p>
<w:p><w:r><w:t>致(单位)：</w:t></w:r><w:r><w:rPr><w:u/></w:rPr><w:t>旧单位</w:t></w:r></w:p>
<w:p><w:r><w:t>事由：</w:t></w:r><w:r><w:rPr><w:u/></w:rPr><w:t>旧事由</w:t></w:r></w:p>
<w:p><w:r><w:t>内容：</w:t></w:r></w:p>
<w:p><w:r><w:rPr><w:u/></w:rPr><w:t>旧内容一</w:t></w:r></w:p>
<w:p><w:r><w:rPr><w:u/></w:rPr><w:t>旧内容二</w:t></w:r></w:p>
<w:p><w:r><w:t>备注：固定备注</w:t></w:r></w:p>
</w:body></w:document>'''


def make_template_docx(path: Path) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", TEMPLATE_XML)
        archive.writestr("custom/unchanged.bin", b"unchanged")


class WorkflowTests(unittest.TestCase):
    def test_selects_cross_platform_cloudstation_roots(self) -> None:
        values = {
            "CLOUDSTATION_ROOT_WINDOWS": r"D:\CloudStaion",
            "CLOUDSTATION_ROOT_MACOS": "~/SynologyDrive/",
            "CLOUDSTATION_ROOT_LINUX": "~/CloudStation",
        }
        self.assertEqual(
            select_cloudstation_root(system_name="Windows", environ=values),
            r"D:\CloudStaion",
        )
        self.assertEqual(
            select_cloudstation_root(system_name="Darwin", environ=values),
            "~/SynologyDrive/",
        )
        self.assertEqual(
            select_cloudstation_root(system_name="Linux", environ=values),
            "~/CloudStation",
        )
        explicit = {**values, "CLOUDSTATION_ROOT": "/explicit/root"}
        self.assertEqual(
            select_cloudstation_root(system_name="Windows", environ=explicit),
            "/explicit/root",
        )

    def test_expands_environment_marker_with_unicode_path(self) -> None:
        original = dict(os.environ)
        try:
            os.environ["CLOUDSTATION_ROOT"] = "/同步根"
            self.assertEqual(
                expand_env("${CLOUDSTATION_ROOT}/示例资料"),
                "/同步根/示例资料",
            )
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_extracts_only_current_underlined_requirement_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.docx"
            make_docx(path)
            result = parse_docx(path)
        self.assertEqual(result.document_no, "给排水-003")
        self.assertEqual(result.document_date, "2026-08-09")
        self.assertEqual(result.subject, "关于测试的事宜")
        self.assertEqual(result.requirement_content, "当前需求第一段\n当前需求第二段")
        self.assertNotIn("已删除", result.requirement_content)
        self.assertNotIn("备注", result.requirement_content)

    def test_scan_build_html_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "给排水-003-2026-08-13_关于测试的事宜"
            folder.mkdir()
            word = folder / "需求工作联系单（给排水-003）_关于测试的事宜.docx"
            make_docx(word)
            (folder / "需求工作联系单（给排水-003）_关于测试的事宜.pdf").write_bytes(
                b"%PDF-1.4\n%%EOF\n"
            )
            records, unmatched, ignored = scan_data_root(root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["discipline"], "给排水")
            self.assertEqual(records[0]["sequence_no"], "003")
            self.assertEqual(records[0]["folder_date"], "2026-08-13")
            self.assertEqual(records[0]["需求内容"], "当前需求第一段\n当前需求第二段")
            self.assertEqual(unmatched, [])
            self.assertEqual(ignored, [])

            data, changed, summary = build_dataset(
                root=root,
                records=records,
                unmatched_files=unmatched,
                ignored_files=ignored,
                previous=None,
            )
            self.assertTrue(changed)
            self.assertEqual(summary["records"], 1)
            self.assertEqual(data["dataset_revision"], 1)
            _, changed_again, _ = build_dataset(
                root=root,
                records=records,
                unmatched_files=unmatched,
                ignored_files=ignored,
                previous=data,
            )
            self.assertFalse(changed_again)

            html_path = root / "summary.html"
            export_summary_html(data, html_path)
            html = html_path.read_text(encoding="utf-8")
            header_tokens = [
                "<th>序号</th>",
                "<span>专业</span>",
                "<th>编号</th>",
                "<th>目录日期</th>",
                "<th>致送单位</th>",
                "<th>主题</th>",
            ]
            positions = [html.index(token) for token in header_tokens]
            self.assertEqual(positions, sorted(positions))
            self.assertIn('id="disciplineFilter"', html)
            self.assertIn('id="statusFilter"', html)
            self.assertIn("row.discipline===discipline", html)
            self.assertIn("row.status===status", html)
            self.assertIn("row.folder_href", html)
            self.assertIn("openDirectory(event,row)", html)
            self.assertIn("/api/open-path", html)
            self.assertIn("/api/create-record", html)
            self.assertIn("buildNewRow()", html)
            self.assertIn("Word 正在导出", html)
            self.assertEqual(validate_dataset(data, root)["errors"], [])
            self.assertEqual(validate_summary_html(html_path, data)["errors"], [])

    def test_resolves_only_relative_directory_inside_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / "给排水-003_示例"
            child.mkdir()
            self.assertEqual(
                resolve_relative_directory(root, "给排水-003_示例"),
                child.resolve(),
            )
            with self.assertRaises(ValueError):
                resolve_relative_directory(root, "../outside")
            with self.assertRaises(ValueError):
                resolve_relative_directory(root, r"C:\Users\sample")
            with self.assertRaises(FileNotFoundError):
                resolve_relative_directory(root, "不存在")

    def test_uses_platform_file_manager_commands(self) -> None:
        path = Path("/tmp/示例目录")
        with patch("multidocu_collator.modules.desktop.subprocess.run") as run:
            open_directory(path, system_name="Darwin")
            run.assert_called_once_with(["open", str(path)], check=True)
        with patch("multidocu_collator.modules.desktop.subprocess.run") as run:
            open_directory(path, system_name="Linux")
            run.assert_called_once_with(["xdg-open", str(path)], check=True)
        with patch(
            "multidocu_collator.modules.desktop.os.startfile", create=True
        ) as startfile:
            open_directory(path, system_name="Windows")
            startfile.assert_called_once_with(str(path))

    def test_local_server_opens_only_valid_relative_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "给排水-001_示例"
            folder.mkdir()
            (root / "summary.html").write_text("<h1>summary</h1>", encoding="utf-8")
            context = AppContext(
                project_root=root,
                data_root=root,
                json_name="data.json",
                html_name="summary.html",
            )
            try:
                server = ThreadingHTTPServer(
                    ("127.0.0.1", 0), _handler_class(context)
                )
            except PermissionError:
                self.skipTest("当前沙箱不允许绑定本机回环端口")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(base + "/", timeout=3) as response:
                    self.assertIn(b"summary", response.read())
                request = urllib.request.Request(
                    base + "/api/open-path",
                    data=json.dumps({"path": folder.name}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch(
                    "multidocu_collator.flows.summary_server_flow.open_directory"
                ) as opener:
                    with urllib.request.urlopen(request, timeout=3) as response:
                        self.assertEqual(response.status, 200)
                    opener.assert_called_once_with(folder.resolve())
                invalid = urllib.request.Request(
                    base + "/api/open-path",
                    data=json.dumps({"path": "../outside"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(invalid, timeout=3)
                self.assertEqual(error.exception.code, 400)
                error.exception.close()
                create_request = urllib.request.Request(
                    base + "/api/create-record",
                    data=json.dumps({"dataset_revision": 1}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch(
                    "multidocu_collator.flows.summary_server_flow.create_record",
                    return_value={"ok": True, "document_code": "消防水-005"},
                ) as creator:
                    with urllib.request.urlopen(create_request, timeout=3) as response:
                        self.assertEqual(response.status, 201)
                    creator.assert_called_once_with(context, {"dataset_revision": 1})
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_summary_embedded_json_escapes_script_markup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = {
                "dataset_revision": 1,
                "records": [{
                    "record_id": "id",
                    "discipline": "给排水",
                    "sequence_no": "001",
                    "folder_date": "2026-01-01",
                    "subject": "</script><script>alert(1)</script>",
                    "需求内容": "测试",
                    "word_fields": {},
                    "files": [],
                    "status": "complete",
                    "warnings": [],
                }],
            }
            output = root / "summary.html"
            export_summary_html(data, output)
            html = output.read_text(encoding="utf-8")
            embedded = html.split('<script id="summaryData" type="application/json">', 1)[1].split("</script>", 1)[0]
            parsed = json.loads(embedded)
            self.assertEqual(parsed["rows"][0]["subject"], "</script><script>alert(1)</script>")
            self.assertNotIn("</script><script>alert(1)", embedded)

    def test_file_labels_distinguish_dwg_and_attachment_pdf(self) -> None:
        data = {
            "dataset_revision": 1,
            "records": [{
                "record_id": "id",
                "discipline": "给排水",
                "sequence_no": "001",
                "folder_date": "2026-01-01",
                "subject": "示例",
                "folder_path": "给排水-001_示例",
                "需求内容": "测试",
                "word_fields": {},
                "status": "complete",
                "warnings": [],
                "files": [
                    {"name": "图纸.dwg", "extension": ".dwg", "role": "drawing_source", "path": "目录/图纸.dwg"},
                    {"name": "附图.pdf", "extension": ".pdf", "role": "attachment_pdf", "path": "目录/附图.pdf"},
                    {"name": "照片.jpg", "extension": ".jpg", "role": "image_attachment", "path": "目录/照片.jpg"},
                ],
            }],
        }
        files = build_summary_view(data)["rows"][0]["files"]
        self.assertEqual(files[0]["role_label"], "DWG")
        self.assertEqual(files[0]["kind_class"], "dwg")
        self.assertEqual(files[1]["role_label"], "附件 PDF")
        self.assertEqual(files[1]["kind_class"], "attachment-pdf")
        self.assertEqual(files[2]["type_label"], "JPG")
        self.assertEqual(files[2]["kind_class"], "")

    def test_generates_docx_from_template_without_changing_other_parts(self) -> None:
        from datetime import date

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "template.docx"
            output = root / "output.docx"
            make_template_docx(template)
            generate_contact_docx(
                template,
                output,
                document_no="给排水-007",
                document_date=date(2026, 8, 17),
                recipient="测试致送单位",
                subject="关于自动生成测试的事宜",
                requirement_content="第一行需求\n第二行需求",
            )
            fields = parse_docx(output)
            self.assertEqual(fields.document_no, "给排水-007")
            self.assertEqual(fields.document_date, "2026-08-17")
            self.assertEqual(fields.project_name, "固定工程")
            self.assertEqual(fields.recipient, "测试致送单位")
            self.assertEqual(fields.subject, "关于自动生成测试的事宜")
            self.assertEqual(fields.requirement_content, "第一行需求\n第二行需求")
            with ZipFile(output) as archive:
                self.assertEqual(archive.read("custom/unchanged.bin"), b"unchanged")

    def test_auto_sequence_and_cross_platform_filename_validation(self) -> None:
        data = {
            "records": [
                {"discipline": "给排水", "sequence_no": "003", "document_code": "给排水-003"},
                {"discipline": "给排水", "sequence_no": "009", "document_code": "给排水-009"},
            ]
        }
        self.assertEqual(next_sequence(data, "给排水"), "010")
        values = _validated_payload(
            {
                "discipline": "消防水",
                "sequence_no": "",
                "folder_date": "2026-08-16",
                "recipient": "示例单位",
                "subject": "关于测试的事宜",
                "requirement_content": "测试内容",
            },
            data,
        )
        self.assertEqual(values["sequence_no"], "001")
        with self.assertRaises(ValueError):
            _validated_payload(
                {
                    "discipline": "消防水",
                    "sequence_no": "002",
                    "folder_date": "2026-08-16",
                    "recipient": "示例单位",
                    "subject": "含/斜杠",
                    "requirement_content": "测试内容",
                },
                data,
            )

    def test_word_pdf_export_uses_platform_automation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docx, pdf = root / "input.docx", root / "output.pdf"
            docx.write_bytes(b"docx")

            def produce_pdf(command, **kwargs):
                pdf.write_bytes(b"%PDF-1.4\n" + b"x" * 120)

            with patch(
                "multidocu_collator.modules.pdf_exporter.subprocess.run",
                side_effect=produce_pdf,
            ) as run:
                export_pdf_with_word(docx, pdf, system_name="Darwin")
            self.assertEqual(run.call_args.args[0][0], "osascript")

    def test_create_record_commits_only_complete_docx_and_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = AppContext(
                project_root=root,
                data_root=root,
                json_name="data.json",
                html_name="summary.html",
                template_name="template.docx",
            )
            (root / "template.docx").write_bytes(b"template")
            (root / "data.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "dataset_revision": 7,
                        "records": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload = {
                "dataset_revision": 7,
                "discipline": "消防水",
                "sequence_no": "005",
                "folder_date": "2026-08-16",
                "recipient": "测试致送单位",
                "subject": "关于保存事务测试的事宜",
                "requirement_content": "测试需求",
            }

            def make_word(template, output, **kwargs):
                output.write_bytes(b"docx")

            def make_pdf(docx, output):
                output.write_bytes(b"%PDF-1.4\n" + b"x" * 120)

            with patch(
                "multidocu_collator.flows.create_record_flow.generate_contact_docx",
                side_effect=make_word,
            ), patch(
                "multidocu_collator.flows.create_record_flow.export_pdf_with_word",
                side_effect=make_pdf,
            ), patch(
                "multidocu_collator.flows.create_record_flow.run_build_archive",
                return_value={"summary": {}},
            ):
                result = create_record(context, payload)
            folder = root / "消防水-005-2026-08-16_关于保存事务测试的事宜"
            self.assertTrue(folder.is_dir())
            self.assertEqual(len(list(folder.glob("*.docx"))), 1)
            self.assertEqual(len(list(folder.glob("*.pdf"))), 1)
            self.assertEqual(result["document_code"], "消防水-005")


if __name__ == "__main__":
    unittest.main()
