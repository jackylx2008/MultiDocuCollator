"""只更新既有联系单需求正文，并重新导出 PDF。"""

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
    """事务式更新 DOCX/PDF；页面只能提交正文和记录定位信息。"""
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
        if content == str(record.get("需求内容") or "").strip():
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
                source_word, staged_word, requirement_content=content
            )
            export_pdf_with_word(staged_word, staged_pdf)
            shutil.copy2(source_word, word_backup)
            pdf_existed = issued_pdf.is_file()
            if pdf_existed:
                shutil.copy2(issued_pdf, pdf_backup)

            staged_word.replace(source_word)
            try:
                staged_pdf.replace(issued_pdf)
                run_build_archive(context)
            except Exception:
                word_backup.replace(source_word)
                if pdf_existed:
                    pdf_backup.replace(issued_pdf)
                elif issued_pdf.exists():
                    issued_pdf.unlink()
                with suppress(Exception):
                    run_build_archive(context)
                raise

        refreshed = load_dataset(context.json_path) or {}
        return {
            "ok": True,
            "changed": True,
            "record_id": record_id,
            "dataset_revision": int(refreshed.get("dataset_revision") or 0),
        }
