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
    renumber_organized_work_contacts,
)
from multidocu_collator.flows.work_contact_mutation import (
    TEMPLATE_NAME,
    create_work_contact,
    delete_work_contact,
    update_work_contact,
)
from multidocu_collator.modules.summary_html import export_summary_html
from multidocu_collator.modules.docx_parser import parse_docx
from multidocu_collator.modules.work_contact import WRITING_SKILL_NAME, scan_work_contacts
from multidocu_collator.modules.work_contact_attachment import read_attachment_docx
from multidocu_collator.modules.work_contact_ai import generate_work_contact_draft, split_work_contact_content
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
    def test_same_day_contacts_follow_sequence_instead_of_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for code, subject in (("质保-023", "消防整改"), ("质保-024", "排水泵整改")):
                folder = root / f"{code}-2026-10-12_{subject}"
                folder.mkdir()
                with ZipFile(folder / f"工作联系单（{code}）_{subject}.docx", "w") as archive:
                    archive.writestr("word/document.xml", STRUCTURAL_TEMPLATE_XML)
            records, _ = scan_work_contacts(root)
            self.assertEqual([record["document_code"] for record in records],
                             ["质保-023", "质保-024"])

    def test_ai_split_previews_body_and_preserves_existing_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / WRITING_SKILL_NAME).write_text("正文概述，附件逐项列明问题。", encoding="utf-8")
            context = AppContext(root, root, "hotel.json", "hotel.html", work_contact_root=root,
                                 local_ai_model="test-model")
            original = "B1层排水泵故障，无法启动。请检查电源并修复。"
            response = {"choices": [{"message": {"content": json.dumps({
                "content": "排水系统存在故障，请修复并反馈；具体问题详见附件。",
                "attachment_content": "1. B1层排水泵无法启动，请检查电源并修复。",
            }, ensure_ascii=False)}}]}
            before = sorted(path.name for path in root.iterdir())
            with (
                patch("multidocu_collator.modules.work_contact_ai._healthcheck", return_value=["test-model"]),
                patch("multidocu_collator.modules.work_contact_ai._request_json", return_value=response) as request,
            ):
                result = split_work_contact_content(root, {
                    "content": original, "attachment_content": "原附件第一项。", "subject": "排水系统整改",
                }, context=context, system_name="Windows")
            self.assertEqual(result["content"], "排水系统存在故障，请修复并反馈；具体问题详见附件。")
            self.assertEqual(result["attachment_content"],
                             "原附件第一项。\n\n1. B1层排水泵无法启动，请检查电源并修复。")
            self.assertIn("正文概述，附件逐项列明问题。",
                          request.call_args.kwargs["payload"]["messages"][0]["content"])
            self.assertEqual(sorted(path.name for path in root.iterdir()), before)

    def test_ai_split_retries_when_model_omits_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / WRITING_SKILL_NAME).write_text("附件逐项列明。", encoding="utf-8")
            context = AppContext(root, root, "hotel.json", "hotel.html", work_contact_root=root,
                                 local_ai_model="test-model")
            def response(content: str, attachment: str) -> dict:
                return {"choices": [{"message": {"content": json.dumps({
                    "content": content, "attachment_content": attachment,
                }, ensure_ascii=False)}}]}
            with (
                patch("multidocu_collator.modules.work_contact_ai._healthcheck", return_value=["test-model"]),
                patch("multidocu_collator.modules.work_contact_ai._request_json", side_effect=[
                    response("请整改。", ""),
                    response("请整改，具体问题详见附件。", "1. 排水泵无法启动，请修复。"),
                ]) as request,
            ):
                result = split_work_contact_content(root, {
                    "content": "排水泵无法启动，请修复。", "subject": "排水泵整改",
                }, context=context, system_name="Windows")
            self.assertEqual(request.call_count, 2)
            self.assertEqual(result["attachment_content"], "1. 排水泵无法启动，请修复。")

    def test_attachment_word_and_pdf_follow_record_edits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with ZipFile(root / TEMPLATE_NAME, "w") as archive:
                archive.writestr("word/document.xml", STRUCTURAL_TEMPLATE_XML)
            build_work_contact_archive(root)

            def fake_pdf(_word: Path, pdf: Path) -> Path:
                writer = PdfWriter()
                writer.add_blank_page(width=595, height=842)
                with pdf.open("wb") as stream:
                    writer.write(stream)
                return pdf

            def dataset() -> dict:
                return json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))

            details = "1. B1层排水泵无法启动，请检查电源。\n\n2. 阀门渗漏，请修复。"
            base = {"discipline": "质保", "folder_date": "2026-10-12", "recipient": "施工单位",
                    "subject": "排水系统整改", "content": "排水系统存在故障，请逐项整改；具体问题详见附件。",
                    "attachment_content": details}
            with patch("multidocu_collator.flows.work_contact_mutation.export_pdf_with_word", side_effect=fake_pdf):
                create_work_contact(root, {**base, "dataset_revision": dataset()["dataset_revision"],
                                           "number_mode": "temporary"})
                record = dataset()["records"][0]
                self.assertEqual(record["附件内容"], details)
                self.assertEqual({item["role"] for item in record["files"]},
                                 {"source_word", "issued_pdf", "attachment_word", "attachment_pdf"})
                attachment = root / next(item["path"] for item in record["files"] if item["role"] == "attachment_word")
                self.assertEqual(read_attachment_docx(attachment), details)
                unrelated_pdf = attachment.parent / "附加说明.pdf"
                fake_pdf(attachment, unrelated_pdf)
                build_work_contact_archive(root)
                revised = details + "\n3. 控制柜报警，请核查。"
                update_work_contact(root, {**base, "attachment_content": revised,
                                           "dataset_revision": dataset()["dataset_revision"],
                                           "record_id": record["record_id"], "number_mode": "keep"})
                record = dataset()["records"][0]
                self.assertEqual(record["附件内容"], revised)
                self.assertTrue(unrelated_pdf.is_file())
                inline_values = {key: value for key, value in base.items() if key != "attachment_content"}
                update_work_contact(root, {**inline_values, "content": "请按附件逐项整改并反馈。",
                                           "dataset_revision": dataset()["dataset_revision"],
                                           "record_id": record["record_id"], "number_mode": "keep"})
                record = dataset()["records"][0]
                self.assertEqual(record["附件内容"], revised)
                update_work_contact(root, {**base, "attachment_content": "",
                                           "dataset_revision": dataset()["dataset_revision"],
                                           "record_id": record["record_id"], "number_mode": "keep"})
                record = dataset()["records"][0]
                self.assertEqual(record["附件内容"], "")
                self.assertEqual({item["role"] for item in record["files"]},
                                 {"source_word", "issued_pdf", "attachment_pdf"})
                self.assertTrue(unrelated_pdf.is_file())

    def test_new_contact_preserves_blank_lines_in_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with ZipFile(root / TEMPLATE_NAME, "w") as archive:
                archive.writestr("word/document.xml", STRUCTURAL_TEMPLATE_XML)
            build_work_contact_archive(root)
            content = "请检查设备。\n\n备注：请同步检查阀门。\n\n　　完成后反馈。"

            def fake_pdf(_word: Path, pdf: Path) -> Path:
                writer = PdfWriter()
                writer.add_blank_page(width=595, height=842)
                with pdf.open("wb") as stream:
                    writer.write(stream)
                return pdf

            with patch("multidocu_collator.flows.work_contact_mutation.export_pdf_with_word", side_effect=fake_pdf):
                revision = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))["dataset_revision"]
                result = create_work_contact(root, {
                    "dataset_revision": revision, "discipline": "质保", "number_mode": "temporary",
                    "folder_date": "2026-10-12", "recipient": "施工单位",
                    "subject": "设备维修", "content": content,
                })
            self.assertTrue(result["ok"])
            data = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))
            record = data["records"][0]
            self.assertEqual(record["内容"], content)
            self.assertEqual(record["original_document_no"], "质保-")
            revised = "请检查设备。\n\n备注：同步检查阀门。\n\n　　完成后提交记录。"
            with patch("multidocu_collator.flows.work_contact_mutation.export_pdf_with_word", side_effect=fake_pdf):
                changed = update_work_contact(root, {
                    "dataset_revision": data["dataset_revision"], "record_id": record["record_id"],
                    "number_mode": "keep", "folder_date": record["folder_date"],
                    "recipient": record["致送单位"], "subject": record["subject"],
                    "content": revised,
                })
            self.assertTrue(changed["changed"])
            refreshed = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))
            self.assertEqual(refreshed["records"][0]["内容"], revised)

    def test_generated_contact_body_starts_at_top_of_template_cell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "template.docx"
            output = root / "generated.docx"
            xml = STRUCTURAL_TEMPLATE_XML.replace(
                "<w:body>",
                '<w:body><w:tbl><w:tr><w:tc><w:tcPr><w:vAlign w:val="center"/></w:tcPr>',
            ).replace("</w:body>", "</w:tc></w:tr></w:tbl></w:body>")
            with ZipFile(source, "w") as archive:
                archive.writestr("word/document.xml", xml)
            write_work_contact_docx(
                source, output, document_no="维保-005", document_date=date(2026, 10, 12),
                recipient="施工单位", subject="防冻措施", content="请落实防冻措施。",
            )
            namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            with ZipFile(output) as archive:
                document = ET.fromstring(archive.read("word/document.xml"))
            alignment = document.find(".//w:tcPr/w:vAlign", namespace)
            self.assertEqual(alignment.get("{%s}val" % namespace["w"]), "top")
            self.assertEqual(parse_docx(output).document_no, "维保-005")
            paragraphs = [
                "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
                for paragraph in document.findall(".//w:p", namespace)
            ]
            footer = next(index for index, text in enumerate(paragraphs) if text.startswith("发出单位"))
            self.assertEqual(paragraphs[footer - 3:footer], ["请落实防冻措施。", "", "以下空白"])
            self.assertEqual(paragraphs.count("以下空白"), 1)
            marker = next(paragraph for paragraph in document.findall(".//w:p", namespace)
                          if "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)) == "以下空白")
            self.assertIsNone(marker.find("./w:pPr/w:ind", namespace))
            with ZipFile(source) as archive:
                original = ET.fromstring(archive.read("word/document.xml"))
            self.assertEqual(original.find(".//w:tcPr/w:vAlign", namespace).get("{%s}val" % namespace["w"]), "center")

    def test_number_modes_keep_temporary_number_out_of_word(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with ZipFile(root / TEMPLATE_NAME, "w") as archive:
                archive.writestr("word/document.xml", STRUCTURAL_TEMPLATE_XML)
            build_work_contact_archive(root)

            def fake_pdf(_word: Path, pdf: Path) -> Path:
                writer = PdfWriter()
                writer.add_blank_page(width=595, height=842)
                with pdf.open("wb") as stream:
                    writer.write(stream)
                return pdf

            def dataset() -> dict:
                return json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))

            base = {"discipline": "质保", "folder_date": "2026-10-12", "recipient": "施工单位",
                    "subject": "排水泵维修", "content": "请检查并维修排水泵。"}
            with patch("multidocu_collator.flows.work_contact_mutation.export_pdf_with_word", side_effect=fake_pdf):
                temporary_record = create_work_contact(root, {
                    **base, "dataset_revision": dataset()["dataset_revision"], "number_mode": "temporary",
                })
                self.assertEqual(temporary_record["document_code"], "质保-001")
                record = dataset()["records"][0]
                self.assertTrue(record["temporary_number"])
                self.assertEqual(record["original_document_no"], "质保-")
                word = root / next(item["path"] for item in record["files"] if item["role"] == "source_word")
                self.assertEqual(parse_docx(word).document_no, "质保-")

                self.assertIn("质保-001", str(word))

                kept = update_work_contact(root, {
                    **base, "subject": "排水泵修复", "dataset_revision": dataset()["dataset_revision"],
                    "record_id": record["record_id"], "number_mode": "keep",
                })
                self.assertTrue(kept["changed"])
                record = dataset()["records"][0]
                self.assertTrue(record["temporary_number"])
                self.assertEqual(record["original_document_no"], "质保-")

                manual = update_work_contact(root, {
                    **base, "subject": "排水泵修复", "dataset_revision": dataset()["dataset_revision"],
                    "record_id": record["record_id"], "number_mode": "manual",
                    "manual_number": "质保-023",
                })
                self.assertIn("质保-023", manual["folder_path"])
                record = dataset()["records"][0]
                self.assertFalse(record["temporary_number"])
                self.assertEqual(record["original_document_no"], "质保-023")
                word = root / next(item["path"] for item in record["files"] if item["role"] == "source_word")
                self.assertEqual(parse_docx(word).document_no, "质保-023")
                with self.assertRaisesRegex(ValueError, "编号已存在"):
                    create_work_contact(root, {
                        **base, "dataset_revision": dataset()["dataset_revision"],
                        "number_mode": "manual", "manual_number": "023",
                    })
                with self.assertRaisesRegex(ValueError, "手动编号"):
                    create_work_contact(root, {
                        **base, "dataset_revision": dataset()["dataset_revision"],
                        "number_mode": "manual", "manual_number": "任意文本",
                    })
                auto = create_work_contact(root, {
                    **base, "subject": "消防设备维修", "dataset_revision": dataset()["dataset_revision"],
                    "number_mode": "auto",
                })
                self.assertEqual(auto["document_code"], "质保-024")
                record = next(item for item in dataset()["records"] if item["document_code"] == "质保-023")
                reverted = update_work_contact(root, {
                    **base, "subject": "排水泵修复", "dataset_revision": dataset()["dataset_revision"],
                    "record_id": record["record_id"], "number_mode": "temporary",
                })
                self.assertIn("质保-025", reverted["folder_path"])
                record = next(item for item in dataset()["records"] if item["document_code"] == "质保-025")
                self.assertTrue(record["temporary_number"])
                self.assertEqual(record["original_document_no"], "质保-")
                word = root / next(item["path"] for item in record["files"] if item["role"] == "source_word")
                self.assertEqual(parse_docx(word).document_no, "质保-")

    def test_edit_preserves_existing_unnumbered_word(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "质保-001-2026-08-09_设备维修"
            folder.mkdir()
            word = folder / "工作联系单（质保-001）_设备维修.docx"
            with ZipFile(word, "w") as archive:
                archive.writestr("word/document.xml", STRUCTURAL_TEMPLATE_XML)
            build_work_contact_archive(root)
            data = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))
            record = data["records"][0]
            self.assertTrue(record["temporary_number"])
            self.assertEqual(record["original_document_no"], "质保—")

            def fake_pdf(_word: Path, pdf: Path) -> Path:
                writer = PdfWriter()
                writer.add_blank_page(width=595, height=842)
                with pdf.open("wb") as stream:
                    writer.write(stream)
                return pdf

            with patch("multidocu_collator.flows.work_contact_mutation.export_pdf_with_word", side_effect=fake_pdf):
                update_work_contact(root, {
                    "dataset_revision": data["dataset_revision"], "record_id": record["record_id"],
                    "number_mode": "keep", "folder_date": "2026-08-10", "recipient": "施工单位",
                    "subject": "设备修复", "content": "请修复设备。",
                })
            refreshed = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))["records"][0]
            self.assertTrue(refreshed["temporary_number"])
            self.assertEqual(refreshed["original_document_no"], "质保—")
    def test_ai_draft_reads_current_writing_rules_and_only_returns_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / WRITING_SKILL_NAME
            skill.write_text("按事实、影响、要求撰写。", encoding="utf-8")
            context = AppContext(root, root, "hotel.json", "hotel.html", work_contact_root=root,
                                 local_ai_model="test-model")
            response = {"choices": [{"message": {"content": json.dumps({
                "recipient": "施工单位", "subject": "事由：关于设备维修事宜",
                "content": "内容：设备故障。具体问题详见附件。\n请落实维修。\n以下空白",
                "attachment_content": "附件：1. 排水泵无法启动，请检查电源。",
                "missing_information": ["请核对整改时限"],
            }, ensure_ascii=False)}}]}
            payload = {"facts": "设备故障，请落实维修。", "discipline": "质保",
                       "folder_date": "2026-10-12"}
            with (
                patch("multidocu_collator.modules.work_contact_ai._healthcheck", return_value=["test-model"]),
                patch("multidocu_collator.modules.work_contact_ai._request_json", return_value=response) as request,
            ):
                first = generate_work_contact_draft(root, payload, context=context, system_name="Windows")
                self.assertIn("按事实、影响、要求撰写。", request.call_args.kwargs["payload"]["messages"][0]["content"])
                skill.write_text("更新规则：只写问题和要求。", encoding="utf-8")
                second = generate_work_contact_draft(root, payload, context=context, system_name="Windows")
                self.assertIn("更新规则：只写问题和要求。", request.call_args.kwargs["payload"]["messages"][0]["content"])
            self.assertEqual(first["subject"], "关于设备维修事宜")
            self.assertEqual(first["content"], "设备故障。具体问题详见附件。\n请落实维修。")
            self.assertEqual(first["attachment_content"], "1. 排水泵无法启动，请检查电源。")
            self.assertEqual(first["missing_information"], ["请核对整改时限"])
            self.assertNotEqual(first["skill_sha256"], second["skill_sha256"])
            self.assertEqual([path.name for path in root.iterdir()], [WRITING_SKILL_NAME])

    def test_ai_draft_retries_fabricated_inspection_and_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / WRITING_SKILL_NAME).write_text("只写事实和要求。", encoding="utf-8")
            context = AppContext(root, root, "hotel.json", "hotel.html", work_contact_root=root,
                                 local_ai_model="test-model")
            def response(content: str) -> dict:
                return {"choices": [{"message": {"content": json.dumps({
                    "recipient": "", "subject": "关于排水泵维修事宜",
                    "content": content, "missing_information": [],
                }, ensure_ascii=False)}}]}
            with (
                patch("multidocu_collator.modules.work_contact_ai._healthcheck", return_value=["test-model"]),
                patch("multidocu_collator.modules.work_contact_ai._request_json", side_effect=[
                    response("经现场核查发现泵故障。请于2026年10月20日前完成。"),
                    response("排水泵运行异常。请排查维修，并反馈完成时间。"),
                ]) as request,
            ):
                result = generate_work_contact_draft(root, {
                    "facts": "排水泵运行异常，只写问题和要求。", "folder_date": "2026-10-12",
                }, context=context, system_name="Windows")
            self.assertEqual(request.call_count, 2)
            self.assertIn("踏勘或检查过程", request.call_args.kwargs["payload"]["messages"][-1]["content"])
            self.assertEqual(result["content"], "排水泵运行异常。请排查维修，并反馈完成时间。")
            self.assertIn("致送单位", result["missing_information"])

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
            paragraphs = [
                "".join(node.text or "" for node in paragraph.iter(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}t"))
                for paragraph in document.iter(f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}p")
            ]
            footer = next(index for index, value in enumerate(paragraphs) if value.startswith("发出单位"))
            self.assertEqual(paragraphs[footer - 4:footer], ["第一段。", "第二段。", "", "以下空白"])
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
            self.assertTrue(records[0]["temporary_number"])
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

    def test_renumber_organized_contacts_separately_by_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, kind in enumerate(("维保", "质保", "质保"), start=1):
                word = root / f"2026-08-{index:02d}_工作联系单_关于设备维修事宜{index}.docx"
                xml = DOCUMENT_XML.replace("质保—", f"{kind}—")
                with ZipFile(word, "w") as archive:
                    archive.writestr("word/document.xml", xml)
            backup = backup_work_contacts(root)
            organize_work_contacts(root, backup, scheme="unified")
            result = renumber_organized_work_contacts(root, backup)
            self.assertEqual(result["by_kind"], {"维保": 1, "质保": 2})
            records, _ = scan_work_contacts(root)
            self.assertEqual(
                [record["document_code"] for record in records],
                ["维保-001", "质保-001", "质保-002"],
            )
            self.assertTrue(all("主体-" not in record["folder_path"] for record in records))

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
                self.assertFalse(record["temporary_number"])
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
                refreshed = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))
                custom = create_work_contact(root, {
                    "dataset_revision": refreshed["dataset_revision"],
                    "discipline": "给排水",
                    "folder_date": "2026-08-11",
                    "recipient": "施工单位",
                    "subject": "管道维修",
                    "content": "请处理。",
                })
                self.assertEqual(custom["document_code"], "给排水-001")
                self.assertTrue((root / custom["folder_path"]).is_dir())

    def test_content_update_uses_scan_attachments_when_no_issued_pdf_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "质保-001-2026-08-09_设备维修"
            folder.mkdir()
            word = folder / "工作联系单（质保-001）_设备维修.docx"
            with ZipFile(word, "w") as archive:
                archive.writestr("word/document.xml", STRUCTURAL_TEMPLATE_XML)
            scan = folder / "工作联系单（质保-001）_设备维修_扫描件.pdf"
            original = PdfWriter()
            original.add_blank_page(width=610, height=800)
            original.add_blank_page(width=430, height=700)
            with scan.open("wb") as stream:
                original.write(stream)
            original_bytes = scan.read_bytes()
            build_work_contact_archive(root)
            data = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))
            record = data["records"][0]
            self.assertFalse(any(item["role"] == "issued_pdf" for item in record["files"]))

            def fake_pdf(_word: Path, pdf: Path) -> Path:
                writer = PdfWriter()
                writer.add_blank_page(width=595, height=842)
                with pdf.open("wb") as stream:
                    writer.write(stream)
                return pdf

            with patch("multidocu_collator.flows.work_contact_mutation.export_pdf_with_word", side_effect=fake_pdf):
                update_work_contact(root, {
                    "dataset_revision": data["dataset_revision"], "record_id": record["record_id"],
                    "number_mode": "keep", "folder_date": record["folder_date"],
                    "recipient": record["致送单位"], "subject": record["subject"],
                    "content": "更新后的维修要求。",
                })
            issued = folder / "工作联系单（质保-001）_设备维修.pdf"
            self.assertTrue(issued.is_file())
            with issued.open("rb") as stream:
                pages = PdfReader(stream).pages
                self.assertEqual(len(pages), 2)
                self.assertEqual(float(pages[0].mediabox.width), 595)
                self.assertEqual(float(pages[1].mediabox.width), 430)
            self.assertEqual(scan.read_bytes(), original_bytes)
            self.assertEqual(parse_docx(word).document_no, "质保—")
            refreshed = json.loads((root / "主体工作联系单数据.json").read_text(encoding="utf-8"))
            self.assertEqual(refreshed["records"][0]["内容"], "更新后的维修要求。")

    def test_flat_documents_are_grouped_and_content_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            word = root / "2026-08-09_工作联系单_关于设备维修事宜.docx"
            with ZipFile(word, "w") as archive:
                archive.writestr("word/document.xml", DOCUMENT_XML)
            (root / f"{word.stem}_扫描件.pdf").write_bytes(b"%PDF-1.4\n")
            (root / "其他文件.txt").write_text("unmatched", encoding="utf-8")
            (root / WRITING_SKILL_NAME).write_text("写作规则", encoding="utf-8")

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
            self.assertTrue(data["writing_skill_available"])
            html = (root / "主体工作联系单汇总.html").read_text(encoding="utf-8")
            self.assertIn("按写作规则生成草稿", html)
            self.assertIn("按状态筛选", html)
            self.assertIn("/api/proofread-work-contact", html)
            self.assertIn("AI 公文修订对照", html)
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
                html = urllib.request.urlopen(url + "work-contact/").read().decode("utf-8")
                self.assertIn("主体工作联系单汇总", html)
                self.assertIn("/api/copy-work-contact-file", html)
                self.assertIn("AI 拆分正文与附件", html)
                self.assertEqual(urllib.request.urlopen(url + "work-contact/sample.pdf").read(), b"%PDF-1.4\n")
                copy_request = urllib.request.Request(
                    url + "api/copy-work-contact-file",
                    data=json.dumps({"path": "sample.pdf"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with patch("multidocu_collator.flows.summary_server_flow.copy_file_to_clipboard") as copier:
                    self.assertTrue(json.load(urllib.request.urlopen(copy_request))["ok"])
                copier.assert_called_once_with((work / "sample.pdf").resolve())
                request = urllib.request.Request(
                    url + "api/refresh-work-contact",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(json.load(urllib.request.urlopen(request))["records"], 0)
                proofread_request = urllib.request.Request(
                    url + "api/proofread-work-contact",
                    data=json.dumps({"content": "原始正文"}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with patch(
                    "multidocu_collator.flows.summary_server_flow.proofread_official_content",
                    return_value="修订正文",
                ) as proofreader:
                    result = json.load(urllib.request.urlopen(proofread_request))
                self.assertEqual(result["revised_content"], "修订正文")
                self.assertTrue(any(part["changed"] for part in result["revised_segments"]))
                proofreader.assert_called_once_with(
                    "原始正文", context=context, content_label="工作联系单正文"
                )
                draft_payload = {"facts": "设备故障", "folder_date": "2026-10-12"}
                draft_request = urllib.request.Request(
                    url + "api/generate-work-contact",
                    data=json.dumps(draft_payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with patch(
                    "multidocu_collator.flows.summary_server_flow.generate_work_contact_draft",
                    return_value={"subject": "设备维修", "content": "请维修。"},
                ) as generator:
                    self.assertEqual(json.load(urllib.request.urlopen(draft_request))["subject"], "设备维修")
                generator.assert_called_once_with(work, draft_payload, context=context)
                split_payload = {"content": "设备故障，请维修。", "subject": "设备维修"}
                split_request = urllib.request.Request(
                    url + "api/split-work-contact",
                    data=json.dumps(split_payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with patch(
                    "multidocu_collator.flows.summary_server_flow.split_work_contact_content",
                    return_value={"content": "请维修，详见附件。", "attachment_content": "1. 设备故障。"},
                ) as splitter:
                    self.assertEqual(json.load(urllib.request.urlopen(split_request))["attachment_content"],
                                     "1. 设备故障。")
                splitter.assert_called_once_with(work, split_payload, context=context)
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
