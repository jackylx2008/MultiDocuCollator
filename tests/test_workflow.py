from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from multidocu_collator.modules.docx_parser import parse_docx
from multidocu_collator.config_loader import expand_env, select_cloudstation_root
from multidocu_collator.modules.repository import build_dataset
from multidocu_collator.modules.scanner import scan_data_root
from multidocu_collator.modules.summary_html import export_summary_html
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
                "<th>主题</th>",
            ]
            positions = [html.index(token) for token in header_tokens]
            self.assertEqual(positions, sorted(positions))
            self.assertIn('id="disciplineFilter"', html)
            self.assertIn('id="statusFilter"', html)
            self.assertIn("row.discipline===discipline", html)
            self.assertIn("row.status===status", html)
            self.assertEqual(validate_dataset(data, root)["errors"], [])
            self.assertEqual(validate_summary_html(html_path, data)["errors"], [])

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


if __name__ == "__main__":
    unittest.main()
