from __future__ import annotations

import json
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from multidocu_collator.context import AppContext
from multidocu_collator.flows.summary_server_flow import create_summary_server
from multidocu_collator.flows.work_contact_flow import build_work_contact_archive
from multidocu_collator.modules.summary_html import export_summary_html
from multidocu_collator.modules.work_contact import scan_work_contacts


DOCUMENT_XML = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>资料编号 质保— 工程名称 示例工程 日 期 2026年8月9日</w:t></w:r></w:p>
<w:p><w:r><w:t>致(单位)：施工单位 事由：关于设备维修事宜</w:t></w:r></w:p>
<w:p><w:r><w:t>内容：</w:t></w:r></w:p>
<w:p><w:r><w:t>设备故障，需要维修。</w:t></w:r></w:p>
<w:p><w:r><w:t>请于本周完成。</w:t></w:r></w:p>
<w:p><w:r><w:t>抄送：工程部</w:t></w:r></w:p>
</w:body></w:document>'''


class WorkContactTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
