"""更新既有联系单主题/需求正文，并重新导出 PDF。"""

from __future__ import annotations

import re
import shutil
import tempfile
import unicodedata
from contextlib import suppress
from pathlib import Path
from typing import Any

from ..constants import TRASH_DIRECTORY_NAME
from ..context import AppContext
from ..modules.desktop import resolve_relative_file
from ..modules.document_generator import update_contact_content
from ..modules.pdf_exporter import export_pdf_with_word
from ..modules.repository import load_dataset
from .build_archive_flow import run_build_archive
from .create_record_flow import _clean_component
from .mutation_lock import RECORD_MUTATION_LOCK


def _validated_requirement_content(value: Any) -> str:
    content = unicodedata.normalize("NFC", str(value or "").strip())
    content = re.sub(r"[ \t]+", " ", content)
    content = re.sub(r" *\r?\n *", "\n", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    if not content:
        raise ValueError("需求内容不能为空")
    if len(content) > 4000:
        raise ValueError("需求内容不能超过 4000 个字符")
    return content


def _record_file(
    context: AppContext, record: dict[str, Any], role: str
) -> Path | None:
    candidates = [
        item
        for item in record.get("files") or []
        if item.get("role") == role and isinstance(item.get("path"), str)
    ]
    if not candidates:
        return None
    return resolve_relative_file(context.data_root, str(candidates[0]["path"]))


def update_record_content(
    context: AppContext, payload: dict[str, Any]
) -> dict[str, Any]:
    """事务式更新 DOCX/PDF，并在主题变化时同步重命名资料目录。"""
    with RECORD_MUTATION_LOCK:
        data = load_dataset(context.json_path)
        if data is None:
            raise FileNotFoundError("JSON 数据库不存在，请先运行 build_archive.py")
        requested_revision = int(payload.get("dataset_revision") or 0)
        current_revision = int(data.get("dataset_revision") or 0)
        if requested_revision != current_revision:
            raise ValueError("页面数据已经更新，请刷新页面后重新操作")

        record_id = str(payload.get("record_id") or "").strip()
        record = next(
            (
                item
                for item in data.get("records") or []
                if item.get("record_id") == record_id
            ),
            None,
        )
        if record is None:
            raise ValueError("待更新记录不存在或已被删除")
        content = _validated_requirement_content(payload.get("requirement_content"))
        current_subject = str(record.get("subject") or "").strip()
        subject = (
            _clean_component(payload.get("subject"), "主题", max_length=120)
            if "subject" in payload
            else None
        )
        subject_changed = subject is not None and subject != current_subject
        content_changed = content != str(record.get("需求内容") or "").strip()
        if not subject_changed and not content_changed:
            return {
                "ok": True,
                "changed": False,
                "dataset_revision": current_revision,
            }

        source_word = _record_file(context, record, "source_word")
        if source_word is None:
            raise FileNotFoundError("当前记录缺少可更新的 Word 联系单")
        issued_pdf = _record_file(context, record, "issued_pdf")
        if issued_pdf is None:
            issued_pdf = source_word.with_suffix(".pdf")
        if issued_pdf.parent != source_word.parent:
            raise ValueError("Word 与联系单 PDF 必须位于同一资料目录")

        source_directory = source_word.parent
        target_directory = source_directory
        final_word_name = source_word.name
        final_pdf_name = issued_pdf.name
        if subject_changed:
            folder_path = str(record.get("folder_path") or "")
            if not folder_path or "/" in folder_path or "\\" in folder_path:
                raise ValueError("当前记录的资料目录结构不支持修改主题")
            expected_source = (context.data_root / folder_path).resolve()
            if expected_source != source_directory.resolve():
                raise ValueError("Word 文件不在记录对应的一级资料目录中")
            document_code = str(record.get("document_code") or "").strip()
            folder_date = str(record.get("folder_date") or "").strip()
            if not document_code or not folder_date:
                raise ValueError("当前记录缺少编号或目录日期，无法修改主题")
            target_directory = context.data_root / (
                f"{document_code}-{folder_date}_{subject}"
            )
            if target_directory.exists():
                raise FileExistsError(f"修改后的资料目录已经存在: {target_directory.name}")
            base_name = f"需求工作联系单（{document_code}）_{subject}"
            final_word_name = f"{base_name}.docx"
            final_pdf_name = f"{base_name}.pdf"
            for current, new_name in (
                (source_word, final_word_name),
                (issued_pdf, final_pdf_name),
            ):
                destination = source_directory / new_name
                if destination.exists() and destination != current:
                    raise FileExistsError(f"修改后的文件已经存在: {new_name}")

        work_root = context.data_root / TRASH_DIRECTORY_NAME
        work_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".update_contact_", dir=work_root
        ) as temporary:
            staging = Path(temporary)
            staged_word = staging / source_word.name
            staged_pdf = staging / issued_pdf.name
            word_backup = staging / f"backup-{source_word.name}"
            pdf_backup = staging / f"backup-{issued_pdf.name}"
            update_contact_content(
                source_word,
                staged_word,
                requirement_content=content,
                subject=subject if subject_changed else None,
            )
            export_pdf_with_word(staged_word, staged_pdf)
            shutil.copy2(source_word, word_backup)
            pdf_existed = issued_pdf.is_file()
            if pdf_existed:
                shutil.copy2(issued_pdf, pdf_backup)

            directory_moved = False
            live_word = source_word
            live_pdf = issued_pdf
            try:
                if subject_changed:
                    source_directory.replace(target_directory)
                    directory_moved = True
                    live_word = target_directory / source_word.name
                    live_pdf = target_directory / issued_pdf.name
                staged_word.replace(live_word)
                staged_pdf.replace(live_pdf)
                final_word = target_directory / final_word_name
                final_pdf = target_directory / final_pdf_name
                if live_word != final_word:
                    live_word.replace(final_word)
                    live_word = final_word
                if live_pdf != final_pdf:
                    live_pdf.replace(final_pdf)
                    live_pdf = final_pdf
                run_build_archive(context)
            except Exception:
                restore_directory = (
                    target_directory if directory_moved else source_directory
                )
                restore_word = restore_directory / source_word.name
                restore_pdf = restore_directory / issued_pdf.name
                if live_word != restore_word and live_word.exists():
                    live_word.unlink()
                word_backup.replace(restore_word)
                if pdf_existed:
                    if live_pdf != restore_pdf and live_pdf.exists():
                        live_pdf.unlink()
                    pdf_backup.replace(restore_pdf)
                elif live_pdf.exists():
                    live_pdf.unlink()
                if directory_moved and target_directory.exists():
                    target_directory.replace(source_directory)
                with suppress(Exception):
                    run_build_archive(context)
                raise

        refreshed = load_dataset(context.json_path) or {}
        return {
            "ok": True,
            "changed": True,
            "record_id": record_id,
            "subject": subject if subject is not None else current_subject,
            "dataset_revision": int(refreshed.get("dataset_revision") or 0),
        }
