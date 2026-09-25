from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfReader, PdfWriter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from multidocu_collator.modules.docx_parser import parse_docx
from multidocu_collator.modules.document_generator import (
    generate_contact_docx,
    update_contact_content,
)
from multidocu_collator.modules.desktop import (
    copy_file_to_clipboard,
    open_directory,
    resolve_relative_directory,
    resolve_relative_file,
)
from multidocu_collator.modules.pdf_exporter import (
    WINDOWS_SCRIPT,
    export_pdf_with_word,
    replace_pdf_first_page,
)
from multidocu_collator.context import AppContext
from multidocu_collator.flows.create_record_flow import (
    _validated_payload,
    create_record,
    next_sequence,
)
from multidocu_collator.flows.delete_record_flow import delete_record
from multidocu_collator.flows.summary_server_flow import (
    _handler_class,
    _open_summary_browser,
)
from multidocu_collator.flows.new_content_draft_flow import (
    clear_new_content_draft,
    load_new_content_draft,
    save_new_content_draft,
)
from multidocu_collator.flows.update_print_status_flow import update_print_statuses
from multidocu_collator.flows.update_record_content_flow import update_record_content
from multidocu_collator.config_loader import (
    expand_env,
    load_common_env,
    select_cloudstation_root,
)
from multidocu_collator.modules.repository import build_dataset
from multidocu_collator.modules.scanner import scan_data_root
from multidocu_collator.modules.summary_html import build_summary_view, export_summary_html
from multidocu_collator.modules.validation import validate_dataset, validate_summary_html
from multidocu_collator.modules.local_ai import (
    build_text_comparison,
    local_ai_status,
    proofread_official_content,
)
from multidocu_collator.modules.archive_migration import migrate_archive


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
<w:p><w:r><w:t>以下空白</w:t></w:r></w:p>
<w:p/><w:p/><w:p/><w:p/>
<w:p><w:r><w:t>抄送: 固定单位</w:t></w:r></w:p>
</w:body></w:document>'''


def make_template_docx(path: Path) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", TEMPLATE_XML)
        archive.writestr("custom/unchanged.bin", b"unchanged")


def make_test_pdf(path: Path, widths: list[int]) -> None:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=800)
    with path.open("wb") as stream:
        writer.write(stream)


def pdf_widths(path: Path) -> list[int]:
    with path.open("rb") as stream:
        return [int(page.mediabox.width) for page in PdfReader(stream).pages]


class WorkflowTests(unittest.TestCase):
    def test_migrates_records_and_writes_offline_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            destination = root / "destination"
            record_dir = source / "暖通空调-001-2026-01-01_测试"
            record_dir.mkdir(parents=True)
            (record_dir / "附件.pdf").write_bytes(b"pdf")
            (source / "酒店需求工作联系单数据.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "records": [
                            {
                                "record_id": str(
                                    uuid.uuid5(
                                        uuid.NAMESPACE_URL,
                                        "hotel-requirement:暖通空调:001",
                                    )
                                ),
                                "需求单已经打印": "是",
                                "作废状态": "否",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = migrate_archive(source, destination)
            copied = (
                destination
                / "暖通空调"
                / record_dir.name
                / "附件.pdf"
            )
            self.assertEqual(result["records"], 1)
            self.assertTrue(copied.is_file())
            self.assertTrue(Path(result["json_path"]).is_file())
            migrated = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(migrated["records"][0]["需求单已经打印"], "是")
            html = Path(result["html_path"]).read_text(encoding="utf-8")
            self.assertIn("导出当前 JSON", html)
            self.assertIn("暖通空调/暖通空调-001-2026-01-01_测试", html)
            self.assertIn('id="disciplineFilter"', html)
            self.assertIn('id="changeFilter"', html)
            self.assertIn("是否需要出变更", html)
            self.assertIn("localeCompare(String(b.document_code", html)
            self.assertIn("tbody tr{height:92px}", html)
            self.assertIn("table-layout:fixed;font-size:14px", html)
            self.assertIn("class=\"cell-scroll\"", html)
            self.assertIn("class=\"subject-link\"", html)
            self.assertIn("roleLabel(f)", html)
            self.assertNotIn(">${esc(f.name)}</a>", html)

    def test_migration_skips_locked_file_and_keeps_other_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            destination = root / "destination"
            record_dir = source / "暖通空调-002-2026-01-02_测试"
            record_dir.mkdir(parents=True)
            (record_dir / "可复制.pdf").write_bytes(b"pdf")
            (record_dir / "被占用.dwg").write_bytes(b"dwg")
            real_copy2 = shutil.copy2

            def copy_with_locked_file(source_file: object, destination_file: object, *args: object, **kwargs: object) -> object:
                if Path(source_file).name == "被占用.dwg":
                    raise PermissionError("file is in use")
                return real_copy2(source_file, destination_file, *args, **kwargs)

            with patch(
                "multidocu_collator.modules.archive_migration.shutil.copy2",
                side_effect=copy_with_locked_file,
            ):
                result = migrate_archive(source, destination)

            target = destination / "暖通空调" / record_dir.name
            self.assertTrue((target / "可复制.pdf").is_file())
            self.assertFalse((target / "被占用.dwg").exists())
            self.assertEqual(len(result["copy_warnings"]), 1)
            migrated = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
            self.assertTrue(any("被占用.dwg" in warning for warning in migrated["records"][0]["warnings"]))

    def test_dotenv_has_priority_over_common_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            (project_root / ".env").write_text(
                "LLAMACPP_API_KEY=dotenv-key\nDOTENV_ONLY=yes\n",
                encoding="utf-8",
            )
            (project_root / "common.env").write_text(
                "LLAMACPP_API_KEY=common-key\nCOMMON_ONLY=yes\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                load_common_env(project_root)
                self.assertEqual(os.environ["LLAMACPP_API_KEY"], "dotenv-key")
                self.assertEqual(os.environ["DOTENV_ONLY"], "yes")
                self.assertEqual(os.environ["COMMON_ONLY"], "yes")

    def test_selects_cross_platform_cloudstation_roots(self) -> None:
        values = {
            "CLOUDSTATION_ROOT_WINDOWS": r"D:\CloudStation",
            "CLOUDSTATION_ROOT_MACOS": "~/SynologyDrive/",
            "CLOUDSTATION_ROOT_LINUX": "~/CloudStation",
        }
        self.assertEqual(
            select_cloudstation_root(system_name="Windows", environ=values),
            r"D:\CloudStation",
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
            (folder / "设备安装附图.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
            records, unmatched, ignored = scan_data_root(root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["discipline"], "给排水")
            self.assertEqual(records[0]["sequence_no"], "003")
            self.assertEqual(records[0]["folder_date"], "2026-08-13")
            self.assertEqual(records[0]["需求内容"], "当前需求第一段\n当前需求第二段")
            figure = next(
                item for item in records[0]["files"] if item["name"] == "设备安装附图.pdf"
            )
            self.assertEqual(figure["role"], "figure_pdf")
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
            self.assertEqual(data["records"][0]["需求单已经打印"], "否")
            self.assertEqual(data["records"][0]["作废状态"], "否")
            rescanned_records = json.loads(json.dumps(records, ensure_ascii=False))
            data["records"][0]["需求单已经打印"] = "是"
            data["records"][0]["作废状态"] = "是"
            preserved, _, _ = build_dataset(
                root=root,
                records=rescanned_records,
                unmatched_files=unmatched,
                ignored_files=ignored,
                previous=data,
            )
            self.assertEqual(preserved["records"][0]["需求单已经打印"], "是")
            self.assertEqual(preserved["records"][0]["作废状态"], "是")
            _, changed_again, _ = build_dataset(
                root=root,
                records=rescanned_records,
                unmatched_files=unmatched,
                ignored_files=ignored,
                previous=data,
            )
            self.assertFalse(changed_again)

            html_path = root / "summary.html"
            export_summary_html(data, html_path)
            html = html_path.read_text(encoding="utf-8")
            generated_at = build_summary_view(data)["generated_at"]
            self.assertRegex(
                generated_at,
                r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
            )
            self.assertNotIn("+08:00", generated_at)
            self.assertNotIn("北京时间", generated_at)
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
            self.assertIn('id="warningMetric"', html)
            self.assertIn('id="warningPreview"', html)
            self.assertIn("function buildWarningPreview()", html)
            self.assertIn("row.warnings.join('；')", html)
            self.assertIn('id="printFilter"', html)
            self.assertIn('id="changeRequiredFilter"', html)
            self.assertIn('id="siteCompletedFilter"', html)
            self.assertIn('id="statusFilter"', html)
            self.assertIn("row.discipline===discipline", html)
            self.assertIn("row.print_status===printStatus", html)
            self.assertIn("row.change_required===changeRequired", html)
            self.assertIn("row.site_completed===siteCompleted", html)
            self.assertIn("row.status===status", html)
            self.assertIn("row.void_status==='是'", html)
            self.assertIn("row.change_required", html)
            self.assertIn("row.site_completed", html)
            self.assertIn("<span>是否需要变更</span>", html)
            self.assertIn("<span>现场是否已经完成</span>", html)
            self.assertIn("th:nth-child(11),td:nth-child(11)", html)
            self.assertIn("min-height:70px", html)
            self.assertIn("row.folder_href", html)
            self.assertIn("openDirectory(event,row)", html)
            self.assertIn("/api/open-path", html)
            self.assertIn("/api/copy-file", html)
            self.assertIn("copyFile(event,file,a)", html)
            self.assertIn("/api/create-record", html)
            self.assertIn("/api/new-content-draft", html)
            self.assertIn("/api/save-new-content-draft", html)
            self.assertIn("临时保存内容", html)
            self.assertIn("不会生成 Word/PDF", html)
            self.assertIn("draft-ai-button ai-button", html)
            self.assertIn("proofreadContent(null,content,draftAiButton", html)
            self.assertIn("if(activeProofread.row)", html)
            self.assertIn("if(activeProofread.onAccept)", html)
            self.assertIn("/api/delete-record", html)
            self.assertIn("/api/refresh-archive", html)
            self.assertIn('id="refreshArchive"', html)
            self.assertIn("refreshArchive(event.currentTarget)", html)
            self.assertIn("<span>需求单已经打印</span>", html)
            self.assertIn('<option value="是">是</option>', html)
            self.assertIn('<option value="否">否</option>', html)
            self.assertIn('id="saveManualStatuses"', html)
            self.assertIn("保存修改内容", html)
            self.assertIn("/api/save-manual-statuses", html)
            self.assertIn("saveManualStatuses(event.currentTarget)", html)
            self.assertIn("void_statuses", html)
            self.assertIn("change_required", html)
            self.assertIn("site_completed", html)
            self.assertIn("void-row", html)
            self.assertIn("repeating-linear-gradient", html)
            self.assertIn("rgba(108,116,124,.28) 10px 14px", html)
            self.assertIn("top:0; z-index:10", html)
            self.assertIn("position:relative; isolation:isolate", html)
            save_script = html.split("async function saveManualStatuses", 1)[1].split(
                "async function deleteRecord", 1
            )[0]
            self.assertNotIn("location.reload()", save_script)
            self.assertIn("data.dataset_revision=Number(result.dataset_revision)", save_script)
            self.assertIn("tableWrap.scrollTop=tableScrollTop", save_script)
            self.assertIn("window.scrollTo(pageScrollX,pageScrollY)", save_script)
            self.assertIn("/api/update-record-content", html)
            self.assertIn('id="manualEditDialog"', html)
            self.assertIn('id="subjectActionDialog"', html)
            self.assertIn("showSubjectActions(row,subjectLink,contentInput)", html)
            self.assertIn("contentInput.readOnly=true", html)
            self.assertIn("node('button','修改','content-button')", html)
            self.assertIn("subject,requirement_content:content", html)
            self.assertIn("/api/proofread-content", html)
            self.assertIn("/api/local-ai-status", html)
            self.assertNotIn("/api/start-local-ai", html)
            self.assertNotIn("/api/stop-local-ai", html)
            self.assertIn('id="aiLight"', html)
            self.assertIn('id="checkLocalAi"', html)
            self.assertIn("检查本地 AI", html)
            self.assertNotIn('id="startLocalAi"', html)
            self.assertNotIn('id="stopLocalAi"', html)
            self.assertNotIn("controlLocalAi", html)
            self.assertIn('id="aiDialog"', html)
            self.assertIn('id="aiOriginalContent"', html)
            self.assertIn('class="comparison-grid"', html)
            self.assertIn("ai-change", html)
            self.assertIn("AI 公文勘误", html)
            self.assertIn("手动修改", html)
            self.assertIn("接受", html)
            self.assertIn("delete-button", html)
            self.assertIn("buildNewRow()", html)
            self.assertIn(".new-row td { padding:6px 4px; vertical-align:top; }", html)
            self.assertIn("discipline-picker", html)
            self.assertIn("disciplinePicker.addEventListener('change'", html)
            self.assertIn("discipline.value=disciplinePicker.value", html)
            self.assertNotIn("disciplineOptions", html)
            self.assertIn(
                "中国建筑第二工程局有限公司国家会议中心二期项目配套部分项目部",
                html,
            )
            self.assertIn("subject.value='关于   的事宜'", html)
            self.assertIn("tableWrap.scrollTop=tableWrap.scrollHeight", html)
            self.assertIn("function scrollToNewEntry()", html)
            self.assertIn("entry.scrollIntoView({block:'end'", html)
            self.assertIn("history.scrollRestoration='manual'", html)
            self.assertIn("[0,120,400]", html)
            self.assertIn("Word 正在导出", html)
            self.assertEqual(validate_dataset(data, root)["errors"], [])
            self.assertEqual(validate_summary_html(html_path, data)["errors"], [])

    def test_new_content_draft_only_saves_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_root = root / "archive"
            data_root.mkdir()
            context = AppContext(
                project_root=root,
                data_root=data_root,
                json_name="data.json",
                html_name="summary.html",
            )

            result = save_new_content_draft(
                context, {"requirement_content": "尚未正式提交的需求内容"}
            )
            loaded = load_new_content_draft(context)

            self.assertEqual(result["characters"], 11)
            self.assertEqual(loaded["requirement_content"], "尚未正式提交的需求内容")
            self.assertFalse(context.json_path.exists())
            self.assertEqual(list(data_root.glob("*.docx")), [])
            self.assertEqual(list(data_root.glob("*.pdf")), [])
            clear_new_content_draft(context)
            self.assertEqual(load_new_content_draft(context)["requirement_content"], "")
            with self.assertRaisesRegex(ValueError, "不能超过 4000"):
                save_new_content_draft(
                    context, {"requirement_content": "字" * 4001}
                )

    def test_scanner_skips_unreadable_file_and_records_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "暖通空调-014-2026-08-26_关于空调的事宜"
            folder.mkdir()
            word = folder / "需求工作联系单（暖通空调-014）_关于空调的事宜.docx"
            make_docx(word)
            pdf = folder / "需求工作联系单（暖通空调-014）_关于空调的事宜.pdf"
            pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
            backup = folder / "A21_002-B2层平面图-A0+1_BIAD.bak"
            backup.write_bytes(b"locked backup")

            def hash_or_deny(path: Path) -> str:
                if path == backup:
                    raise PermissionError(13, "Permission denied", str(path))
                return "test-hash"

            with patch(
                "multidocu_collator.modules.scanner.sha256_file",
                side_effect=hash_or_deny,
            ):
                records, unmatched, ignored = scan_data_root(root)

            self.assertEqual(len(records), 1)
            self.assertEqual(unmatched, [])
            self.assertEqual(ignored, [])
            self.assertNotIn(
                backup.name,
                {item["name"] for item in records[0]["files"]},
            )
            self.assertTrue(
                any(
                    backup.name in warning and "没有读取权限" in warning
                    for warning in records[0]["warnings"]
                )
            )

    def test_updates_print_status_and_rejects_stale_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = AppContext(
                project_root=root,
                data_root=root,
                json_name="data.json",
                html_name="summary.html",
            )
            data = {
                "schema_version": 1,
                "dataset_revision": 3,
                "created_at": "2026-08-21T10:00:00+08:00",
                "updated_at": "2026-08-21T10:00:00+08:00",
                "records": [
                    {
                        "record_id": "record-1",
                        "discipline": "给排水",
                        "sequence_no": "001",
                        "folder_date": "2026-08-21",
                        "subject": "测试",
                        "folder_path": "给排水-001_测试",
                        "需求内容": "测试内容",
                        "word_fields": {},
                        "files": [],
                        "status": "complete",
                        "warnings": [],
                        "需求单已经打印": "否",
                        "作废状态": "否",
                        "是否需要变更": "否",
                        "现场是否已经完成": "否",
                    }
                ],
                "changes": [],
            }
            context.json_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )

            result = update_print_statuses(
                context,
                {
                    "dataset_revision": 3,
                    "statuses": {"record-1": "是"},
                    "void_statuses": {"record-1": "是"},
                    "change_required": {"record-1": "是"},
                    "site_completed": {"record-1": "是"},
                },
            )
            saved = json.loads(context.json_path.read_text(encoding="utf-8"))
            self.assertEqual(result["changed"], 4)
            self.assertEqual(result["changed_print"], 1)
            self.assertEqual(result["changed_void"], 1)
            self.assertEqual(result["changed_change_required"], 1)
            self.assertEqual(result["changed_site_completed"], 1)
            self.assertEqual(result["dataset_revision"], 4)
            self.assertEqual(saved["records"][0]["需求单已经打印"], "是")
            self.assertEqual(saved["records"][0]["作废状态"], "是")
            self.assertEqual(saved["records"][0]["是否需要变更"], "是")
            self.assertEqual(saved["records"][0]["现场是否已经完成"], "是")
            self.assertEqual(saved["changes"][-4]["action"], "print_status_updated")
            self.assertEqual(saved["changes"][-3]["action"], "void_status_updated")
            self.assertEqual(saved["changes"][-2]["action"], "change_required_updated")
            self.assertEqual(saved["changes"][-1]["action"], "site_completed_updated")
            self.assertIn('"print_status":"是"', context.html_path.read_text(encoding="utf-8"))
            self.assertIn('"void_status":"是"', context.html_path.read_text(encoding="utf-8"))

            with self.assertRaisesRegex(ValueError, "页面数据已经更新"):
                update_print_statuses(
                    context,
                    {"dataset_revision": 3, "statuses": {"record-1": "否"}},
                )

    def test_local_ai_status_and_proofreading(self) -> None:
        context = AppContext(
            project_root=PROJECT_ROOT,
            data_root=PROJECT_ROOT,
            json_name="data.json",
            html_name="summary.html",
            local_ai_api_key="test-token",
        )
        with patch(
            "multidocu_collator.modules.local_ai._healthcheck",
            return_value=[context.local_ai_model.removesuffix(".gguf")],
        ):
            status = local_ai_status(context, system_name="Windows")
        self.assertTrue(status["available"])
        with patch(
            "multidocu_collator.modules.local_ai._healthcheck",
            return_value=["other-model.gguf"],
        ):
            missing_status = local_ai_status(context, system_name="Windows")
        self.assertFalse(missing_status["available"])
        with patch(
            "multidocu_collator.modules.local_ai._healthcheck",
            return_value=[context.local_ai_model.removesuffix(".gguf")],
        ), patch(
            "multidocu_collator.modules.local_ai._request_json",
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": "请相关单位复核并书面回复。\n以下空白"
                        }
                    }
                ]
            },
        ) as request:
            revised = proofread_official_content(
                "请相关单位复合并书面回复。",
                context=context,
                system_name="Windows",
            )
        self.assertEqual(revised, "请相关单位复核并书面回复。")
        self.assertFalse(request.call_args.kwargs["payload"]["stream"])
        self.assertEqual(
            request.call_args.kwargs["payload"]["model"],
            context.local_ai_model.removesuffix(".gguf"),
        )
        self.assertEqual(request.call_args.kwargs["api_key"], "test-token")
        system_prompt = request.call_args.kwargs["payload"]["messages"][0]["content"]
        self.assertIn("优化句式、语序和逻辑衔接", system_prompt)
        self.assertIn("准确、简洁、庄重的公文用语", system_prompt)
        self.assertIn("平方米写为 m²", system_prompt)
        self.assertIn("千瓦写为 kW", system_prompt)
        self.assertIn("如果输入中出现则删除", system_prompt)
        self.assertIn("如果输入中没有也不得新增", system_prompt)
        with patch(
            "multidocu_collator.modules.local_ai._healthcheck",
            return_value=[context.local_ai_model],
        ), patch(
            "multidocu_collator.modules.local_ai._request_json",
            return_value={
                "choices": [
                    {"message": {"content": "设备功率调整为 5 kW。\n以下空白"}}
                ]
            },
        ) as marker_request:
            removed_marker = proofread_official_content(
                "设备功率调整为五千瓦。\n以下空白",
                context=context,
                system_name="Windows",
            )
        self.assertEqual(removed_marker, "设备功率调整为 5 kW。")
        self.assertNotIn("以下空白", removed_marker)
        marker_user_prompt = marker_request.call_args.kwargs["payload"]["messages"][
            1
        ]["content"]
        self.assertNotIn("以下空白", marker_user_prompt)
        original_segments, revised_segments = build_text_comparison(
            "请相关单位复合并回复。", "请相关单位复核并书面回复。"
        )
        self.assertEqual(
            "".join(segment["text"] for segment in original_segments),
            "请相关单位复合并回复。",
        )
        self.assertEqual(
            "".join(segment["text"] for segment in revised_segments),
            "请相关单位复核并书面回复。",
        )
        self.assertTrue(any(segment["changed"] for segment in original_segments))
        self.assertTrue(any(segment["changed"] for segment in revised_segments))
        with self.assertRaisesRegex(RuntimeError, "仅支持 Windows"):
            proofread_official_content(
                "测试",
                context=context,
                system_name="Linux",
            )

    def test_llamacpp_status_only_checks_external_service(self) -> None:
        context = AppContext(
            project_root=PROJECT_ROOT,
            data_root=PROJECT_ROOT,
            json_name="data.json",
            html_name="summary.html",
        )
        with patch(
            "multidocu_collator.modules.local_ai._healthcheck",
            side_effect=RuntimeError("连接被拒绝"),
        ) as healthcheck:
            status = local_ai_status(context, system_name="Windows")
        self.assertFalse(status["available"])
        self.assertIn("未启用或不可用", status["message"])
        healthcheck.assert_called_once_with(context)

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

            document = child / "示例.pdf"
            document.write_bytes(b"%PDF-1.4\n")
            self.assertEqual(
                resolve_relative_file(root, f"{child.name}/示例.pdf"),
                document.resolve(),
            )
            with self.assertRaises(ValueError):
                resolve_relative_file(root, "../outside.pdf")
            with self.assertRaises(FileNotFoundError):
                resolve_relative_file(root, f"{child.name}/不存在.pdf")

    def test_scanner_excludes_recoverable_trash_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trash = root / "_trash"
            trash.mkdir()
            (trash / "给排水-001-2026-01-01_已删除记录").mkdir()
            records, unmatched, ignored = scan_data_root(
                root, generated_names={"_trash"}
            )
            self.assertEqual(records, [])
            self.assertEqual(unmatched, [])
            self.assertEqual(ignored, ["_trash"])

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
        with self.assertRaisesRegex(RuntimeError, "仅支持 Windows"):
            copy_file_to_clipboard(path, system_name="Linux")

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
                draft_request = urllib.request.Request(
                    base + "/api/save-new-content-draft",
                    data=json.dumps(
                        {"requirement_content": "接口临时草稿"}, ensure_ascii=False
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(draft_request, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                with urllib.request.urlopen(
                    base + "/api/new-content-draft", timeout=3
                ) as response:
                    draft_result = json.load(response)
                self.assertEqual(draft_result["requirement_content"], "接口临时草稿")
                with patch(
                    "multidocu_collator.flows.summary_server_flow.local_ai_status",
                    return_value={
                        "supported": True,
                        "available": True,
                        "system": "Windows",
                        "model": context.local_ai_model,
                        "message": "已就绪",
                    },
                ) as status_checker:
                    with urllib.request.urlopen(
                        base + "/api/local-ai-status", timeout=3
                    ) as response:
                        self.assertEqual(response.status, 200)
                    status_checker.assert_called_once_with(context)
                start_request = urllib.request.Request(
                    base + "/api/start-local-ai",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as start_error:
                    urllib.request.urlopen(start_request, timeout=3)
                self.assertEqual(start_error.exception.code, 404)
                start_error.exception.close()
                stop_request = urllib.request.Request(
                    base + "/api/stop-local-ai",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as stop_error:
                    urllib.request.urlopen(stop_request, timeout=3)
                self.assertEqual(stop_error.exception.code, 404)
                stop_error.exception.close()
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
                source_file = folder / "资料.pdf"
                source_file.write_bytes(b"%PDF-1.4\n")
                copy_request = urllib.request.Request(
                    base + "/api/copy-file",
                    data=json.dumps({"path": f"{folder.name}/资料.pdf"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch(
                    "multidocu_collator.flows.summary_server_flow.copy_file_to_clipboard"
                ) as copier:
                    with urllib.request.urlopen(copy_request, timeout=3) as response:
                        self.assertEqual(response.status, 200)
                    copier.assert_called_once_with(source_file.resolve())
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
                refresh_request = urllib.request.Request(
                    base + "/api/refresh-archive",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch(
                    "multidocu_collator.flows.summary_server_flow.run_build_archive",
                    return_value={"changed": True, "summary": {"records": 1}},
                ) as refresher:
                    with urllib.request.urlopen(refresh_request, timeout=3) as response:
                        self.assertEqual(response.status, 200)
                    refresher.assert_called_once_with(context)
                print_payload = {
                    "dataset_revision": 1,
                    "statuses": {"id": "是"},
                    "void_statuses": {"id": "是"},
                }
                print_request = urllib.request.Request(
                    base + "/api/save-manual-statuses",
                    data=json.dumps(print_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch(
                    "multidocu_collator.flows.summary_server_flow.update_print_statuses",
                    return_value={"ok": True, "changed": 1, "dataset_revision": 2},
                ) as updater:
                    with urllib.request.urlopen(print_request, timeout=3) as response:
                        self.assertEqual(response.status, 200)
                    updater.assert_called_once_with(context, print_payload)
                content_payload = {
                    "dataset_revision": 1,
                    "record_id": "id",
                    "subject": "更新主题",
                    "requirement_content": "更新内容",
                }
                content_request = urllib.request.Request(
                    base + "/api/update-record-content",
                    data=json.dumps(content_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch(
                    "multidocu_collator.flows.summary_server_flow.update_record_content",
                    return_value={"ok": True, "changed": True},
                ) as content_updater:
                    with urllib.request.urlopen(content_request, timeout=3) as response:
                        self.assertEqual(response.status, 200)
                    content_updater.assert_called_once_with(context, content_payload)
                proofread_request = urllib.request.Request(
                    base + "/api/proofread-content",
                    data=json.dumps(
                        {"requirement_content": "原始内容"}, ensure_ascii=False
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch(
                    "multidocu_collator.flows.summary_server_flow.proofread_official_content",
                    return_value="修订内容",
                ) as proofreader:
                    with urllib.request.urlopen(proofread_request, timeout=3) as response:
                        self.assertEqual(response.status, 200)
                        proofread_result = json.load(response)
                    self.assertEqual(proofread_result["revised_content"], "修订内容")
                    self.assertTrue(proofread_result["original_segments"])
                    self.assertTrue(proofread_result["revised_segments"])
                    proofreader.assert_called_once_with(
                        "原始内容",
                        context=context,
                    )
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
                delete_request = urllib.request.Request(
                    base + "/api/delete-record",
                    data=json.dumps(
                        {"dataset_revision": 1, "record_id": "id", "folder_path": folder.name}
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with patch(
                    "multidocu_collator.flows.summary_server_flow.delete_record",
                    return_value={"ok": True, "trash_path": f"_trash/{folder.name}"},
                ) as deleter:
                    with urllib.request.urlopen(delete_request, timeout=3) as response:
                        self.assertEqual(response.status, 200)
                    deleter.assert_called_once_with(
                        context,
                        {
                            "dataset_revision": 1,
                            "record_id": "id",
                            "folder_path": folder.name,
                        },
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_windows_browser_launch_is_detached_from_code_runner(self) -> None:
        module = "multidocu_collator.flows.summary_server_flow.subprocess"
        with (
            patch(f"{module}.DETACHED_PROCESS", 0x00000008, create=True),
            patch(f"{module}.CREATE_NEW_PROCESS_GROUP", 0x00000200, create=True),
            patch(f"{module}.CREATE_NO_WINDOW", 0x08000000, create=True),
            patch(f"{module}.CREATE_BREAKAWAY_FROM_JOB", 0x01000000, create=True),
            patch(f"{module}.Popen") as launcher,
            patch(
                "multidocu_collator.flows.summary_server_flow.webbrowser.open"
            ) as browser_open,
        ):
            _open_summary_browser(
                "http://127.0.0.1:12345/", system_name="Windows"
            )

        launcher.assert_called_once()
        self.assertEqual(
            launcher.call_args.args[0],
            ["cmd.exe", "/d", "/c", "start", "", "http://127.0.0.1:12345/"],
        )
        self.assertEqual(
            launcher.call_args.kwargs["creationflags"],
            0x00000008 | 0x00000200 | 0x08000000 | 0x01000000,
        )
        browser_open.assert_not_called()

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

    def test_file_labels_distinguish_dwg_figure_and_attachment_pdf(self) -> None:
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
                    {"name": "说明.pdf", "extension": ".pdf", "role": "attachment_pdf", "path": "目录/说明.pdf"},
                    {"name": "照片.jpg", "extension": ".jpg", "role": "image_attachment", "path": "目录/照片.jpg"},
                ],
            }],
        }
        files = build_summary_view(data)["rows"][0]["files"]
        self.assertEqual(files[0]["role_label"], "DWG")
        self.assertEqual(files[0]["kind_class"], "dwg")
        self.assertEqual(files[0]["path"], "目录/图纸.dwg")
        self.assertEqual(files[1]["role_label"], "PDF附图")
        self.assertEqual(files[1]["kind_class"], "figure-pdf")
        self.assertEqual(files[2]["role_label"], "附件 PDF")
        self.assertEqual(files[2]["kind_class"], "attachment-pdf")
        self.assertEqual(files[3]["type_label"], "JPG")
        self.assertEqual(files[3]["kind_class"], "")

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

            updated_output = root / "updated-output.docx"
            update_contact_content(
                output,
                updated_output,
                requirement_content="更新后的第一项需求\n更新后的第二项需求",
                subject="关于同时修改主题和内容的事宜",
            )
            updated_fields = parse_docx(updated_output)
            self.assertEqual(updated_fields.document_no, fields.document_no)
            self.assertEqual(updated_fields.document_date, fields.document_date)
            self.assertEqual(updated_fields.recipient, fields.recipient)
            self.assertEqual(updated_fields.subject, "关于同时修改主题和内容的事宜")
            self.assertEqual(
                updated_fields.requirement_content,
                "更新后的第一项需求\n更新后的第二项需求",
            )
            with ZipFile(updated_output) as archive:
                self.assertEqual(archive.read("custom/unchanged.bin"), b"unchanged")

            long_output = root / "long-output.docx"
            long_line = (
                "请相关单位根据现场情况完成设备、管线及控制系统调整，并在实施后提交完整记录和验收资料。"
                "同时复核相关技术参数、安装位置和联动逻辑，确认无误后完成书面回复。"
            )
            generate_contact_docx(
                template,
                long_output,
                document_no="给排水-008",
                document_date=date(2026, 8, 17),
                recipient="测试致送单位",
                subject="关于动态空白测试的事宜",
                requirement_content="\n".join([long_line] * 4),
            )
            with ZipFile(long_output) as archive:
                document = ET.fromstring(archive.read("word/document.xml"))
            namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragraphs = list(document.iter(namespace + "p"))
            texts = [
                "".join(node.text or "" for node in paragraph.iter(namespace + "t"))
                for paragraph in paragraphs
            ]
            marker_index = texts.index("以下空白")
            copy_index = next(
                index for index in range(marker_index + 1, len(texts))
                if texts[index].replace(" ", "").startswith("抄送:")
            )
            self.assertEqual(
                sum(not text.strip() for text in texts[marker_index + 1 : copy_index]),
                0,
            )

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

            pdf.unlink()
            with patch(
                "multidocu_collator.modules.pdf_exporter.subprocess.run",
                side_effect=produce_pdf,
            ) as run:
                export_pdf_with_word(docx, pdf, system_name="Windows")
            command = run.call_args.args[0]
            environment = run.call_args.kwargs["env"]
            self.assertEqual(command[0], "powershell.exe")
            self.assertEqual(command[-1], WINDOWS_SCRIPT)
            self.assertEqual(environment["MULTIDOCU_INPUT_PATH"], str(docx.resolve()))
            self.assertEqual(environment["MULTIDOCU_OUTPUT_PATH"], str(pdf.resolve()))

    def test_replaces_pdf_first_page_and_preserves_following_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original.pdf"
            replacement = root / "replacement.pdf"
            output = root / "output.pdf"
            make_test_pdf(original, [500, 600, 700])
            make_test_pdf(replacement, [900])

            replace_pdf_first_page(original, replacement, output)

            self.assertEqual(pdf_widths(output), [900, 600, 700])
            self.assertEqual(pdf_widths(original), [500, 600, 700])

            make_test_pdf(replacement, [900, 901])
            with self.assertRaisesRegex(ValueError, "必须恰好为一页"):
                replace_pdf_first_page(original, replacement, output)
            self.assertFalse(output.exists())

    def test_updates_existing_subject_and_content_and_reissues_pdf(self) -> None:
        from datetime import date

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "给排水-001-2026-08-24_测试事项"
            folder.mkdir()
            template = root / "template.docx"
            word = folder / "需求工作联系单（给排水-001）_测试事项.docx"
            pdf = folder / "需求工作联系单（给排水-001）_测试事项.pdf"
            make_template_docx(template)
            generate_contact_docx(
                template,
                word,
                document_no="给排水-001",
                document_date=date(2026, 8, 24),
                recipient="测试单位",
                subject="测试事项",
                requirement_content="原需求内容",
            )
            make_test_pdf(pdf, [500, 600])
            data = {
                "schema_version": 1,
                "dataset_revision": 5,
                "records": [
                    {
                        "record_id": "record-1",
                        "document_code": "给排水-001",
                        "folder_date": "2026-08-24",
                        "folder_path": folder.name,
                        "subject": "测试事项",
                        "需求内容": "原需求内容",
                        "files": [
                            {
                                "role": "source_word",
                                "path": f"{folder.name}/{word.name}",
                            },
                            {
                                "role": "issued_pdf",
                                "path": f"{folder.name}/{pdf.name}",
                            },
                        ],
                    }
                ],
            }
            (root / "data.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            context = AppContext(
                project_root=root,
                data_root=root,
                json_name="data.json",
                html_name="summary.html",
            )

            def export_pdf(_: Path, output: Path) -> Path:
                make_test_pdf(output, [900])
                return output

            with patch(
                "multidocu_collator.flows.update_record_content_flow.export_pdf_with_word",
                side_effect=export_pdf,
            ), patch(
                "multidocu_collator.flows.update_record_content_flow.run_build_archive",
                side_effect=[RuntimeError("刷新失败"), {"changed": False}],
            ):
                with self.assertRaisesRegex(RuntimeError, "刷新失败"):
                    update_record_content(
                        context,
                        {
                            "dataset_revision": 5,
                            "record_id": "record-1",
                            "subject": "不应保留的主题",
                            "requirement_content": "不应保留的内容",
                        },
                    )
            self.assertEqual(parse_docx(word).requirement_content, "原需求内容")
            self.assertEqual(parse_docx(word).subject, "测试事项")
            self.assertTrue(folder.is_dir())
            self.assertEqual(pdf_widths(pdf), [500, 600])

            with patch(
                "multidocu_collator.flows.update_record_content_flow.export_pdf_with_word",
                side_effect=export_pdf,
            ), patch(
                "multidocu_collator.flows.update_record_content_flow.run_build_archive",
                return_value={"changed": True},
            ) as rebuild:
                result = update_record_content(
                    context,
                    {
                        "dataset_revision": 5,
                        "record_id": "record-1",
                        "requirement_content": "修订后的需求内容",
                    },
                )
            self.assertTrue(result["changed"])
            self.assertEqual(parse_docx(word).requirement_content, "修订后的需求内容")
            self.assertEqual(pdf_widths(pdf), [900, 600])
            rebuild.assert_called_once_with(context)

            revised_subject = "关于修改后测试事项的事宜"
            with patch(
                "multidocu_collator.flows.update_record_content_flow.export_pdf_with_word",
                side_effect=export_pdf,
            ), patch(
                "multidocu_collator.flows.update_record_content_flow.run_build_archive",
                return_value={"changed": True},
            ):
                result = update_record_content(
                    context,
                    {
                        "dataset_revision": 5,
                        "record_id": "record-1",
                        "subject": revised_subject,
                        "requirement_content": "主题和正文均已修改",
                    },
                )
            revised_folder = root / f"给排水-001-2026-08-24_{revised_subject}"
            revised_base = f"需求工作联系单（给排水-001）_{revised_subject}"
            revised_word = revised_folder / f"{revised_base}.docx"
            revised_pdf = revised_folder / f"{revised_base}.pdf"
            self.assertTrue(result["changed"])
            self.assertFalse(folder.exists())
            self.assertTrue(revised_folder.is_dir())
            self.assertEqual(parse_docx(revised_word).subject, revised_subject)
            self.assertEqual(
                parse_docx(revised_word).requirement_content,
                "主题和正文均已修改",
            )
            self.assertEqual(pdf_widths(revised_pdf), [900, 600])

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

    def test_delete_record_moves_directory_to_trash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder_name = "消防水-005-2026-08-16_关于删除测试的事宜"
            source = root / folder_name
            source.mkdir()
            (source / "evidence.txt").write_text("保留", encoding="utf-8")
            context = AppContext(root, root, "data.json", "summary.html")
            (root / "data.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "dataset_revision": 4,
                        "records": [{"record_id": "record-1", "folder_path": folder_name}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch(
                "multidocu_collator.flows.delete_record_flow.run_build_archive",
                return_value={"summary": {}},
            ):
                result = delete_record(
                    context,
                    {
                        "dataset_revision": 4,
                        "record_id": "record-1",
                        "folder_path": folder_name,
                    },
                )
            destination = root / result["trash_path"]
            self.assertFalse(source.exists())
            self.assertEqual(
                (destination / "evidence.txt").read_text(encoding="utf-8"), "保留"
            )

    def test_delete_record_rolls_back_when_database_refresh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder_name = "给排水-008-2026-08-16_关于回滚测试的事宜"
            source = root / folder_name
            source.mkdir()
            context = AppContext(root, root, "data.json", "summary.html")
            (root / "data.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "dataset_revision": 5,
                        "records": [{"record_id": "record-2", "folder_path": folder_name}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch(
                "multidocu_collator.flows.delete_record_flow.run_build_archive",
                side_effect=RuntimeError("refresh failed"),
            ):
                with self.assertRaises(RuntimeError):
                    delete_record(
                        context,
                        {
                            "dataset_revision": 5,
                            "record_id": "record-2",
                            "folder_path": folder_name,
                        },
                    )
            self.assertTrue(source.is_dir())
            self.assertEqual(list((root / "_trash").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
