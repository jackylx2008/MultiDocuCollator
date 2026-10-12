from __future__ import annotations

import json
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from pypdf import PdfReader, PdfWriter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from multidocu_collator.context import AppContext
from multidocu_collator.flows.summary_server_flow import create_summary_server
from multidocu_collator.flows.work_contact_flow import build_work_contact_archive
from multidocu_collator.flows.work_contact_migration import (
    backup_work_contacts,
    organize_work_contacts,
    plan_work_contact_organization,
)
from multidocu_collator.flows.work_contact_mutation import (
    TEMPLATE_NAME,
    create_work_contact,
    delete_work_contact,
    update_work_contact,
)
from multidocu_collator.modules.summary_html import export_summary_html
from multidocu_collator.modules.work_contact import scan_work_contacts
from multidocu_collator.modules.work_contact_document import write_work_contact_docx


DOCUMENT_XML = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>资料编号 质保— 工程名称 示例工程 日 期 2026年8月9日</w:t></w:r></w:p>
<w:p><w:r><w:t>致(单位)：施工单位 事由：关于设备维修事宜</w:t></w:r></w:p>
<w:p><w:r><w:t>内容：</w:t></w:r></w:p>
<w:p><w:r><w:t>设备故障，需要维修。</w:t></w:r></w:p>
<w:p><w:r><w:t>请于本周完成。</w:t></w:r></w:p>
<w:p><w:r><w:t>抄送：工程部</w:t></w:r></w:p>
</w:body></w:document>'''

STRUCTURAL_TEMPLATE_XML = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>资料编号</w:t></w:r></w:p><w:p><w:r><w:t>质保—</w:t></w:r></w:p>
<w:p><w:r><w:t>工程名称</w:t></w:r></w:p><w:p><w:r><w:t>示例工程</w:t></w:r></w:p>
<w:p><w:r><w:t>日 期</w:t></w:r></w:p><w:p><w:r><w:t>2026年8月9日</w:t></w:r></w:p>
<w:p><w:r><w:t>致(单位)：施工单位</w:t></w:r></w:p>
<w:p><w:r><w:t>事由：关于设备维修事宜</w:t></w:r></w:p>
<w:p><w:r><w:t>内容：</w:t></w:r></w:p>
<w:p><w:r><w:t>原始正文。</w:t></w:r></w:p>
<w:p><w:r><w:t>以下空白</w:t></w:r></w:p>
<w:p><w:r><w:t>发出单位：工程部</w:t></w:r></w:p>
</w:body></w:document>'''


class WorkContactTests(unittest.TestCase):
    def test_rewrite_preserves_namespaces_and_handles_repeated_body_label(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.docx"
            output = root / "output.docx"
            xml = STRUCTURAL_TEMPLATE_XML.replace(
                '<w:p><w:r><w:t>原始正文。</w:t></w:r></w:p>',
                '<w:p><w:r><w:t>内容：</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>原始正文。以下空白</w:t></w:r></w:p>',
            ).replace(
                '<w:document xmlns:w=',
                '<w:document xmlns:other="urn:structural-test" xmlns:w=',
            ).replace(
                '</w:body>', '<other:marker/></w:body>',
            )
            with ZipFile(source, "w") as archive:
                archive.writestr("word/document.xml", xml)
            write_work_contact_docx(
                source, output,
                document_no="主体-001",
                document_date=date(2026, 8, 10),
                recipient="总包单位",
                subject="设备修复",
                content="第一段。\n第二段。",
            )
            with ZipFile(output) as archive:
                document = ET.fromstring(archive.read("word/document.xml"))
            self.assertIsNotNone(document.find(".//{urn:structural-test}marker"))
            records_root = root / "archive"
            records_root.mkdir()
            archived = records_root / "2026-08-10_工作联系单_设备修复.docx"
            archived.write_bytes(output.read_bytes())
            records, _ = scan_work_contacts(records_root)
            self.assertEqual(records[0]["内容"], "第一段。\n第二段。")

    def test_backup_preserves_nested_files_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "收文").mkdir()
            (root / "收文" / "回复.pdf").write_bytes(b"%PDF-1.4\n")
            (root / "联系单.docx").write_bytes(b"word")
            backup = backup_work_contacts(root)
            manifest = json.loads((backup / "backup_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {item["path"] for item in manifest["files"]},
                {"收文/回复.pdf", "联系单.docx"},
            )
            self.assertEqual((backup / "收文" / "回复.pdf").read_bytes(), b"%PDF-1.4\n")
            self.assertEqual((backup / "联系单.docx").read_bytes(), b"word")

    def test_organize_flat_contacts_into_one_folder_per_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "2026-08-09_工作联系单_关于设备维修事宜.docx"
            with ZipFile(first, "w") as archive:
                archive.writestr("word/document.xml", DOCUMENT_XML)
            (root / f"{first.stem}_扫描件.pdf").write_bytes(b"scan")
            (root / f"{first.stem} - 副本.docx").write_bytes(b"copy")
            (root / "未匹配.txt").write_text("keep", encoding="utf-8")
            backup = backup_work_contacts(root)
            plan = plan_work_contact_organization(root, scheme="unified")
            self.assertEqual(len(plan), 1)
            self.assertEqual(plan[0]["code"], "主体-001")
            result = organize_work_contacts(root, backup, scheme="unified")
            self.assertEqual(result["records"], 1)
            folder = root / "主体-001-2026-08-09_关于设备维修事宜"
            self.assertTrue((folder / "工作联系单（主体-001）_关于设备维修事宜.docx").is_file())
            self.assertTrue((folder / "工作联系单（主体-001）_关于设备维修事宜_扫描件.pdf").is_file())
            self.assertTrue((folder / "工作联系单（主体-001）_关于设备维修事宜_副本.docx").is_file())
            self.assertTrue((backup / first.name).is_file())
            self.assertEqual((root / "未匹配.txt").read_text(encoding="utf-8"), "keep")
            records, unmatched = scan_work_contacts(root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["document_code"], "主体-001")
            self.assertEqual(unmatched, ["未匹配.txt"])

    def test_organize_restores_flat_files_when_archive_build_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            word = root / "2026-08-09_工作联系单_关于设备维修事宜.docx"
            with ZipFile(word, "w") as archive:
                archive.writestr("word/document.xml", DOCUMENT_XML)
            original = word.read_bytes()
            backup = backup_work_contacts(root)
            with patch(
                "multidocu_collator.flows.work_contact_migration.build_work_contact_archive",
                side_effect=RuntimeError("archive failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "archive failed"):
                    organize_work_contacts(root, backup, scheme="unified")
            self.assertEqual(word.read_bytes(), original)
            self.assertFalse((root / "主体-001-2026-08-09_关于设备维修事宜").exists())
            self.assertTrue((backup / word.name).is_file())

    def test_create_update_and_delete_organized_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / TEMPLATE_NAME
            with ZipFile(template, "w") as archive:
                archive.writestr("word/document.xml", STRUCTURAL_TEMPLATE_XML)
            build_work_contact_archive(root)
            initial_revision = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))["dataset_revision"]

            def fake_pdf(_word: Path, pdf: Path) -> Path:
                writer = PdfWriter()
                writer.add_blank_page(width=595, height=842)
                with pdf.open("wb") as stream:
                    writer.write(stream)
                return pdf

            create_payload = {
                "dataset_revision": initial_revision,
                "discipline": "主体",
                "folder_date": "2026-08-09",
                "recipient": "施工单位",
                "subject": "关于设备维修事宜",
                "content": "设备故障，需要维修。",
            }
            with patch(
                "multidocu_collator.flows.work_contact_mutation.export_pdf_with_word",
                side_effect=fake_pdf,
            ):
                created = create_work_contact(root, create_payload)
                self.assertEqual(created["document_code"], "主体-001")
                data = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))
                record = data["records"][0]
                issued = root / next(item["path"] for item in record["files"] if item["role"] == "issued_pdf")
                extra = PdfWriter()
                with issued.open("rb") as stream:
                    extra.append(PdfReader(stream))
                extra.add_blank_page(width=595, height=842)
                with issued.open("wb") as stream:
                    extra.write(stream)
                build_work_contact_archive(root)
                data = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))
                record = data["records"][0]
                updated = update_work_contact(root, {
                    "dataset_revision": data["dataset_revision"],
                    "record_id": record["record_id"],
                    "folder_date": "2026-08-10",
                    "recipient": "总包单位",
                    "subject": "关于设备修复事宜",
                    "content": "请完成设备修复。",
                })
                self.assertTrue(updated["changed"])
                self.assertTrue((root / "主体-001-2026-08-10_关于设备修复事宜").is_dir())
                new_pdf = next((root / "主体-001-2026-08-10_关于设备修复事宜").glob("*.pdf"))
                self.assertEqual(len(PdfReader(new_pdf).pages), 2)
                data = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))
                self.assertEqual(data["records"][0]["内容"], "请完成设备修复。")
                deleted = delete_work_contact(root, {
                    "dataset_revision": data["dataset_revision"],
                    "record_id": data["records"][0]["record_id"],
                    "folder_path": data["records"][0]["folder_path"],
                })
                self.assertTrue((root / deleted["trash_path"]).is_dir())
                self.assertEqual(len(json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))["records"]), 0)

    def test_flat_documents_are_grouped_and_content_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            word = root / "2026-08-09_工作联系单_关于设备维修事宜.docx"
            with ZipFile(word, "w") as archive:
                archive.writestr("word/document.xml", DOCUMENT_XML)
            (root / f"{word.stem}_扫描件.pdf").write_bytes(b"%PDF-1.4\n")
            (root / "其他文件.txt").write_text("unmatched", encoding="utf-8")

            records, unmatched = scan_work_contacts(root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["内容"], "设备故障，需要维修。\n请于本周完成。")
            self.assertEqual(records[0]["status"], "complete")
            self.assertEqual([item["role"] for item in records[0]["files"]], ["source_word", "signed_scan"])
            self.assertEqual(unmatched, ["其他文件.txt"])

            result = build_work_contact_archive(root)
            self.assertEqual(result["records"], 1)
            self.assertFalse(build_work_contact_archive(root)["changed"])
            data = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))
            self.assertEqual(data["dataset_revision"], 1)
            html = (root / "主体工作联系单汇总.html").read_text(encoding="utf-8")
            self.assertIn("按状态筛选", html)
            self.assertNotIn("workflow-nav", html)
            self.assertNotIn("酒店需求单", html)
            hotel_html = root / "hotel.html"
            export_summary_html({"records": []}, hotel_html)
            self.assertNotIn("workContactLink", hotel_html.read_text(encoding="utf-8"))

    def test_python_entry_uses_gui_chooser(self) -> None:
        import serve_summary

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = {
                "log_level": "INFO",
                "data_root": str(root),
                "json_name": "hotel.json",
                "html_name": "hotel.html",
                "template_name": "template.docx",
                "local_ai_base_url": "http://127.0.0.1:8080/v1",
                "local_ai_model": "test",
                "local_ai_api_key": "",
                "local_ai_request_timeout_sec": 30,
                "work_contact_root": str(root),
            }
            with (
                patch.object(serve_summary, "configure_utf8_stdio"),
                patch.object(serve_summary, "setup_logger"),
                patch.object(serve_summary, "load_settings", return_value=settings),
                patch.object(serve_summary, "run_build_archive"),
                patch.object(serve_summary, "build_work_contact_archive"),
                patch.object(serve_summary, "_run_control_window") as chooser,
                patch.object(sys, "argv", ["serve_summary.py"]),
            ):
                self.assertEqual(serve_summary.main(), 0)
                chooser.assert_called_once()

    def test_chooser_buttons_open_only_selected_workflow(self) -> None:
        import serve_summary

        buttons = []

        class Widget:
            def __init__(self, *_args, **kwargs):
                if "text" in kwargs and "command" in kwargs:
                    buttons.append(kwargs)

            def pack(self, **_kwargs):
                pass

            def configure(self, **_kwargs):
                pass

            def title(self, *_args):
                pass

            def resizable(self, *_args):
                pass

            def geometry(self, *_args):
                pass

            def iconbitmap(self, **_kwargs):
                pass

            def protocol(self, *_args):
                pass

            def mainloop(self):
                pass

        class StringVar:
            def __init__(self, **_kwargs):
                pass

            def set(self, _value):
                pass

        fake_tkinter = types.SimpleNamespace(
            Button=Widget, Frame=Widget, Label=Widget, StringVar=StringVar, Tk=Widget
        )
        server = types.SimpleNamespace(serve_forever=lambda: None, server_close=lambda: None)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "主体工作联系单汇总.html").write_text("ready", encoding="utf-8")
            context = AppContext(root, root, "hotel.json", "hotel.html", work_contact_root=root)
            with (
                patch.dict(sys.modules, {"tkinter": fake_tkinter}),
                patch.object(serve_summary, "create_summary_server", return_value=(server, "http://127.0.0.1:1234/")),
                patch.object(serve_summary, "_open_summary_browser") as open_browser,
            ):
                serve_summary._run_control_window(context)
                self.assertEqual([item["text"] for item in buttons], ["酒店需求单", "主体工作联系单", "停止服务"])
                open_browser.assert_not_called()
                buttons[0]["command"]()
                buttons[1]["command"]()
                self.assertEqual(
                    [call.args[0] for call in open_browser.call_args_list],
                    ["http://127.0.0.1:1234/", "http://127.0.0.1:1234/work-contact/"],
                )

    def test_server_serves_work_contact_files_with_root_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            hotel = base / "hotel"
            work = base / "work"
            hotel.mkdir()
            work.mkdir()
            (hotel / "hotel.html").write_text("hotel", encoding="utf-8")
            (work / "sample.pdf").write_bytes(b"%PDF-1.4\n")
            build_work_contact_archive(work)
            context = AppContext(base, hotel, "hotel.json", "hotel.html", work_contact_root=work)
            server, url = create_summary_server(context)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertIn("主体工作联系单汇总", urllib.request.urlopen(url + "work-contact/").read().decode("utf-8"))
                self.assertEqual(urllib.request.urlopen(url + "work-contact/sample.pdf").read(), b"%PDF-1.4\n")
                request = urllib.request.Request(
                    url + "api/refresh-work-contact",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(json.load(urllib.request.urlopen(request))["records"], 0)
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(url + "work-contact/%2e%2e/hotel/hotel.html")
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_server_creates_and_deletes_work_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            hotel = base / "hotel"
            work = base / "work"
            hotel.mkdir()
            work.mkdir()
            (hotel / "hotel.html").write_text("hotel", encoding="utf-8")
            with ZipFile(work / TEMPLATE_NAME, "w") as archive:
                archive.writestr("word/document.xml", STRUCTURAL_TEMPLATE_XML)
            build_work_contact_archive(work)
            revision = json.loads((work / "主体工作联系单数据.json").read_text(encoding="utf-8"))["dataset_revision"]
            context = AppContext(base, hotel, "hotel.json", "hotel.html", work_contact_root=work)
            server, url = create_summary_server(context)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def post(route: str, payload: dict) -> dict:
                request = urllib.request.Request(
                    url + route,
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                return json.load(urllib.request.urlopen(request))

            def fake_pdf(_word: Path, pdf: Path) -> Path:
                writer = PdfWriter()
                writer.add_blank_page(width=595, height=842)
                with pdf.open("wb") as stream:
                    writer.write(stream)
                return pdf

            try:
                with patch(
                    "multidocu_collator.flows.work_contact_mutation.export_pdf_with_word",
                    side_effect=fake_pdf,
                ):
                    created = post("api/create-work-contact", {
                        "dataset_revision": revision,
                        "discipline": "主体",
                        "folder_date": "2026-08-09",
                        "recipient": "施工单位",
                        "subject": "关于设备维修事宜",
                        "content": "设备故障，需要维修。",
                    })
                    self.assertEqual(created["document_code"], "主体-001")
                    data = json.loads((work / "主体工作联系单数据.json").read_text(encoding="utf-8"))
                    record = data["records"][0]
                    deleted = post("api/delete-work-contact", {
                        "dataset_revision": data["dataset_revision"],
                        "record_id": record["record_id"],
                        "folder_path": record["folder_path"],
                    })
                    self.assertTrue((work / deleted["trash_path"]).is_dir())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
