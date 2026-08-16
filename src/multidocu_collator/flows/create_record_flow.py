"""从 HTML 新增一条联系单并刷新 JSON/HTML。"""

from __future__ import annotations

import re
import tempfile
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from ..context import AppContext
from ..modules.document_generator import generate_contact_docx
from ..modules.pdf_exporter import export_pdf_with_word
from ..modules.repository import load_dataset
from .build_archive_flow import run_build_archive
from .mutation_lock import RECORD_MUTATION_LOCK


INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _clean_component(value: Any, field: str, *, max_length: int = 120) -> str:
    text = unicodedata.normalize("NFC", str(value or "").strip())
    text = re.sub(r"\s+", " ", text)
    if not text:
        raise ValueError(f"{field}不能为空")
    if len(text) > max_length:
        raise ValueError(f"{field}不能超过 {max_length} 个字符")
    if INVALID_FILENAME.search(text) or text.endswith((".", " ")):
        raise ValueError(f"{field}含有 Windows/macOS 不兼容的文件名字符")
    if text.split(".", 1)[0].upper() in WINDOWS_RESERVED:
        raise ValueError(f"{field}不能使用系统保留名称")
    return text


def next_sequence(data: dict[str, Any], discipline: str) -> str:
    numbers = [
        int(str(record.get("sequence_no") or "0"))
        for record in data.get("records") or []
        if record.get("discipline") == discipline
        and str(record.get("sequence_no") or "").isdigit()
    ]
    return str((max(numbers) if numbers else 0) + 1).zfill(3)


def _validated_payload(payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    discipline = _clean_component(payload.get("discipline"), "专业", max_length=30)
    if "-" in discipline:
        raise ValueError("专业不能包含连字符“-”")
    raw_sequence = str(payload.get("sequence_no") or "").strip()
    sequence = raw_sequence or next_sequence(data, discipline)
    if not sequence.isdigit() or int(sequence) <= 0:
        raise ValueError("编号必须是大于 0 的数字")
    sequence = sequence.zfill(max(3, len(sequence)))
    try:
        document_date = date.fromisoformat(str(payload.get("folder_date") or ""))
    except ValueError as exc:
        raise ValueError("目录日期必须是有效的 YYYY-MM-DD 日期") from exc
    recipient = _clean_component(payload.get("recipient"), "致送单位", max_length=100)
    subject = _clean_component(payload.get("subject"), "主题", max_length=120)
    requirement = unicodedata.normalize(
        "NFC", str(payload.get("requirement_content") or "").strip()
    )
    requirement = re.sub(r"[ \t]+", " ", requirement)
    requirement = re.sub(r" *\r?\n *", "\n", requirement)
    requirement = re.sub(r"\n{3,}", "\n\n", requirement)
    if not requirement:
        raise ValueError("需求内容不能为空")
    if len(requirement) > 4000:
        raise ValueError("需求内容不能超过 4000 个字符")
    code = f"{discipline}-{sequence}"
    if any(record.get("document_code") == code for record in data.get("records") or []):
        raise ValueError(f"编号“{code}”已经存在")
    return {
        "discipline": discipline,
        "sequence_no": sequence,
        "folder_date": document_date,
        "recipient": recipient,
        "subject": subject,
        "requirement_content": requirement,
        "document_code": code,
    }


def create_record(context: AppContext, payload: dict[str, Any]) -> dict[str, Any]:
    with RECORD_MUTATION_LOCK:
        data = load_dataset(context.json_path)
        if data is None:
            raise FileNotFoundError("JSON 数据库不存在，请先运行 build_archive.py")
        requested_revision = int(payload.get("dataset_revision") or 0)
        current_revision = int(data.get("dataset_revision") or 0)
        if requested_revision != current_revision:
            raise ValueError("页面数据已经更新，请刷新页面后重新填写")
        values = _validated_payload(payload, data)
        existing_prefix = f"{values['document_code']}-"
        if any(
            item.is_dir() and item.name.startswith(existing_prefix)
            for item in context.data_root.iterdir()
        ):
            raise FileExistsError(f"编号“{values['document_code']}”对应的目录已经存在")
        folder_name = (
            f"{values['document_code']}-{values['folder_date'].isoformat()}_"
            f"{values['subject']}"
        )
        final_directory = context.data_root / folder_name
        if final_directory.exists():
            raise FileExistsError(f"目标目录已经存在: {folder_name}")
        if not context.template_path.is_file():
            raise FileNotFoundError(f"联系单模板不存在: {context.template_path}")
        base_name = f"需求工作联系单（{values['document_code']}）_{values['subject']}"
        with tempfile.TemporaryDirectory(prefix=".new_contact_", dir=context.data_root) as temp:
            staging = Path(temp) / folder_name
            staging.mkdir()
            docx = staging / f"{base_name}.docx"
            pdf = staging / f"{base_name}.pdf"
            generate_contact_docx(
                context.template_path,
                docx,
                document_no=values["document_code"],
                document_date=values["folder_date"],
                recipient=values["recipient"],
                subject=values["subject"],
                requirement_content=values["requirement_content"],
            )
            export_pdf_with_word(docx, pdf)
            staging.replace(final_directory)
            try:
                run_build_archive(context)
            except Exception:
                if final_directory.exists() and not staging.exists():
                    final_directory.replace(staging)
                raise
        return {
            "ok": True,
            "folder_path": folder_name,
            "document_code": values["document_code"],
            "dataset_revision": int(
                (load_dataset(context.json_path) or {}).get("dataset_revision") or 0
            ),
        }
