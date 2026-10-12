from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from multidocu_collator.context import AppContext
from multidocu_collator.flows.summary_server_flow import create_summary_server
from multidocu_collator.flows.work_contact_flow import build_work_contact_archive
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
            self.assertIn("酒店需求单", html)

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
