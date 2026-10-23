"""主体工作联系单的新增、修改与可恢复删除。"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..modules.desktop import resolve_relative_directory, resolve_relative_file
from ..modules.file_utils import sha256_file
from ..modules.pdf_exporter import assemble_work_contact_pdf, export_pdf_with_word
from ..modules.work_contact_attachment import (
    METADATA_NAME, read_attachment_metadata, write_attachment_docx,
    write_attachment_metadata,
)
from ..modules.work_contact_document import write_work_contact_docx
from ..modules.work_contact import TEMPLATE_NAME, TEMPLATE_NAMES
from .create_record_flow import _clean_component
from .delete_record_flow import _trash_destination
from .mutation_lock import RECORD_MUTATION_LOCK
from .work_contact_flow import JSON_NAME, build_work_contact_archive


def _load_current(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = root / JSON_NAME
    if not path.is_file():
        raise FileNotFoundError("主体工作联系单数据库不存在，请先重新扫描")
    data = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("dataset_revision") or 0) != int(data.get("dataset_revision") or 0):
        raise ValueError("页面数据已经更新，请刷新页面后重新操作")
    return data


def _clean_content(value: Any, *, label: str = "内容", required: bool = True, limit: int = 10000) -> str:
    content = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    content = re.sub(r"[ \t]+", " ", content)
    content = re.sub(r" *\n *", "\n", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    if required and not content:
        raise ValueError(f"{label}不能为空")
    if len(content) > limit:
        raise ValueError(f"{label}不能超过 {limit} 个字符")
    return content


def _values(payload: dict[str, Any], *, current_attachment: str = "") -> dict[str, Any]:
    try:
        document_date = date.fromisoformat(str(payload.get("folder_date") or ""))
    except ValueError as exc:
        raise ValueError("日期必须是有效的 YYYY-MM-DD 日期") from exc
    return {
        "folder_date": document_date,
        "recipient": _clean_component(payload.get("recipient"), "致送单位", max_length=100),
        "subject": _clean_component(payload.get("subject"), "主题", max_length=120),
        "content": _clean_content(payload.get("content")),
        "attachment_content": _clean_content(
            payload.get("attachment_content", current_attachment),
            label="附件内容", required=False, limit=20000,
        ),
    }


def _folder_name(code: str, document_date: date, subject: str) -> str:
    return f"{code}-{document_date.isoformat()}_{subject}"


def _base_name(code: str, subject: str) -> str:
    return f"工作联系单（{code}）_{subject}"


def _attachment_name(code: str, subject: str) -> str:
    return f"附件（{code}）_{subject}"


def _next_code(records: list[dict[str, Any]], discipline: str) -> str:
    numbers = [
        int(str(record.get("sequence_no") or "0"))
        for record in records
        if record.get("discipline") == discipline
        and str(record.get("sequence_no") or "").isdigit()
    ]
    return f"{discipline}-{(max(numbers) if numbers else 0) + 1:03d}"


def _manual_code(discipline: str, value: Any) -> str:
    raw = str(value or "").strip()
    match = re.fullmatch(rf"(?:{re.escape(discipline)}[-—－])?([0-9]{{1,6}})", raw)
    if match is None or int(match[1]) == 0:
        raise ValueError("手动编号须为 1 至 6 位正整数，可输入序号或类别-序号")
    sequence = f"{int(match[1]):03d}"
    return f"{discipline}-{sequence}"


def _numbering(
    records: list[dict[str, Any]], discipline: str, payload: dict[str, Any],
    *, current: dict[str, Any] | None = None,
) -> tuple[str, bool, str]:
    mode = str(payload.get("number_mode") or ("keep" if current else "auto"))
    if mode == "keep" and current is not None:
        code = str(current.get("document_code") or "")
        temporary = bool(current.get("temporary_number"))
        document_no = str(current.get("original_document_no") or ("" if temporary else code))
        return code, temporary, document_no
    if mode not in {"auto", "temporary", "manual"}:
        raise ValueError("编号方式无效")
    others = [record for record in records if current is None or record.get("record_id") != current.get("record_id")]
    code = (_manual_code(discipline, payload.get("manual_number")) if mode == "manual"
            else _next_code(others, discipline))
    if any(record.get("document_code") == code for record in others):
        raise ValueError(f"编号已存在：{code}")
    temporary = mode == "temporary"
    return code, temporary, f"{discipline}-" if temporary else code


def create_work_contact(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    with RECORD_MUTATION_LOCK:
        root = root.resolve(strict=True)
        data = _load_current(root, payload)
        values = _values(payload)
        discipline = _clean_component(payload.get("discipline"), "类别", max_length=30)
        if "-" in discipline:
            raise ValueError("类别不能包含连字符")
        code, temporary, document_no = _numbering(data.get("records") or [], discipline, payload)
        folder_name = _folder_name(code, values["folder_date"], values["subject"])
        final = root / folder_name
        if final.exists():
            raise FileExistsError(f"联系单目录已存在: {folder_name}")
        template = root / TEMPLATE_NAMES.get(discipline, TEMPLATE_NAME)
        if not template.is_file():
            template = root / TEMPLATE_NAME
        if not template.is_file():
            raise FileNotFoundError(f"缺少{discipline}工作联系单模板")
        base = _base_name(code, values["subject"])
        with tempfile.TemporaryDirectory(prefix=".new_work_contact_", dir=root) as temporary:
            staging = Path(temporary) / folder_name
            staging.mkdir()
            word = staging / f"{base}.docx"
            pdf = staging / f"{base}.pdf"
            write_work_contact_docx(
                template, word,
                document_no=document_no,
                document_date=values["folder_date"],
                recipient=values["recipient"],
                subject=values["subject"],
                content=values["content"],
            )
            generated_pdf = staging / f".{base}.generated.pdf"
            export_pdf_with_word(word, generated_pdf)
            if values["attachment_content"]:
                attachment_base = _attachment_name(code, values["subject"])
                attachment_word = staging / f"{attachment_base}.docx"
                attachment_pdf = staging / f"{attachment_base}.pdf"
                write_attachment_docx(
                    attachment_word, subject=values["subject"],
                    content=values["attachment_content"],
                )
                export_pdf_with_word(attachment_word, attachment_pdf)
                pages = assemble_work_contact_pdf(generated_pdf, pdf, attachment=attachment_pdf)
                write_attachment_metadata(staging, values["attachment_content"], pages)
                attachment_word.unlink()
                attachment_pdf.unlink()
                generated_pdf.unlink()
            else:
                generated_pdf.replace(pdf)
            staging.replace(final)
            try:
                build_work_contact_archive(root)
            except Exception:
                final.replace(staging)
                raise
        refreshed = json.loads((root / JSON_NAME).read_text(encoding="utf-8"))
        return {
            "ok": True,
            "document_code": code,
            "temporary_number": temporary,
            "folder_path": folder_name,
            "dataset_revision": refreshed["dataset_revision"],
        }


def _record_for_update(root: Path, payload: dict[str, Any]) -> tuple[dict, dict]:
    data = _load_current(root, payload)
    record_id = str(payload.get("record_id") or "")
    record = next(
        (item for item in data.get("records") or [] if item.get("record_id") == record_id),
        None,
    )
    if record is None:
        raise ValueError("联系单不存在或已被删除")
    return data, record


def delete_work_contact(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    with RECORD_MUTATION_LOCK:
        root = root.resolve(strict=True)
        _, record = _record_for_update(root, payload)
        relative = str(record.get("folder_path") or "")
        if not relative or relative != payload.get("folder_path"):
            raise ValueError("记录目录与当前数据不一致")
        source = resolve_relative_directory(root, relative)
        if source.parent != root or source.is_symlink():
            raise ValueError("只允许删除一级联系单目录")
        trash = root / "_trash"
        trash.mkdir(exist_ok=True)
        destination = _trash_destination(trash, source.name)
        if destination.resolve().parent != trash.resolve():
            raise ValueError("回收目录越界")
        source.replace(destination)
        try:
            build_work_contact_archive(root)
        except Exception:
            destination.replace(source)
            raise
        refreshed = json.loads((root / JSON_NAME).read_text(encoding="utf-8"))
        return {
            "ok": True,
            "trash_path": destination.relative_to(root).as_posix(),
            "dataset_revision": refreshed["dataset_revision"],
        }


def update_work_contact(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """保留旧版完整目录到 _trash，再发布新版 Word/PDF 与目录。"""
    with RECORD_MUTATION_LOCK:
        root = root.resolve(strict=True)
        data, record = _record_for_update(root, payload)
        values = _values(payload, current_attachment=str(record.get("附件内容") or ""))
        code, temporary, document_no = _numbering(
            data.get("records") or [], str(record.get("discipline") or ""), payload,
            current=record,
        )
        if not code or not record.get("folder_path"):
            raise ValueError("当前联系单尚未整理成独立目录")
        source_dir = resolve_relative_directory(root, str(record["folder_path"]))
        if source_dir.parent != root or source_dir.is_symlink():
            raise ValueError("只允许修改资料根目录下的一级联系单")
        target_dir = root / _folder_name(code, values["folder_date"], values["subject"])
        if target_dir != source_dir and target_dir.exists():
            raise FileExistsError(f"目标目录已存在: {target_dir.name}")
        if target_dir.resolve().parent != root:
            raise ValueError("目标目录越出资料根目录")
        changed = (
            values["folder_date"].isoformat() != record.get("folder_date")
            or values["subject"] != record.get("subject")
            or values["recipient"] != record.get("致送单位")
            or values["content"] != record.get("内容")
            or values["attachment_content"] != str(record.get("附件内容") or "")
            or code != record.get("document_code")
            or temporary != bool(record.get("temporary_number"))
            or document_no != str(record.get("original_document_no") or ("" if temporary else record.get("document_code") or ""))
        )
        if not changed:
            return {"ok": True, "changed": False, "dataset_revision": data["dataset_revision"]}
        for item in record.get("files") or []:
            if item.get("role") not in {
                "source_word", "issued_pdf", "signed_scan", "attachment_word", "attachment_pdf",
            }:
                continue
            path = resolve_relative_file(root, str(item.get("path") or ""))
            if sha256_file(path) != item.get("sha256"):
                raise ValueError(f"资料文件已在外部修改，请先重新扫描刷新：{path.name}")
        word_item = next(
            (item for item in record.get("files") or [] if item.get("role") == "source_word"),
            None,
        )
        if word_item is None:
            raise FileNotFoundError("当前记录缺少 Word 联系单")
        source_word = resolve_relative_file(root, str(word_item["path"]))
        if source_word.parent != source_dir:
            raise ValueError("Word 文件不在联系单一级目录")
        issued_item = next(
            (item for item in record.get("files") or [] if item.get("role") == "issued_pdf"),
            None,
        )
        signed_item = next(
            (item for item in record.get("files") or [] if item.get("role") == "signed_scan"),
            None,
        )
        # 旧资料可能只有扫描件；用它的后续页面作为新 PDF 的附件来源，原扫描件仍保留。
        source_pdf_item = issued_item or signed_item
        source_pdf = (
            resolve_relative_file(root, str(source_pdf_item["path"])) if source_pdf_item else None
        )
        previous_metadata = read_attachment_metadata(source_dir)
        if source_pdf and source_pdf.parent != source_dir:
            raise ValueError("PDF 文件不在联系单一级目录")
        trash = root / "_trash"
        trash.mkdir(exist_ok=True)
        token = uuid4().hex[:10]
        staging = trash / f".update_pending_{token}"
        snapshot = trash / f"更新前_{source_dir.name}_{token}"
        if any(path.resolve().parent != trash.resolve() for path in (staging, snapshot)):
            raise ValueError("更新暂存目录越界")
        shutil.copytree(source_dir, staging)
        base_name = _base_name(code, values["subject"])
        new_word = staging / f"{base_name}.docx"
        new_pdf = staging / f"{base_name}.pdf"
        write_work_contact_docx(
            source_word,
            new_word,
            document_no=document_no,
            document_date=values["folder_date"],
            recipient=values["recipient"],
            subject=(
                values["subject"] if values["subject"] != record["subject"]
                else str(record.get("word_subject") or values["subject"])
            ),
            content=values["content"],
        )
        generated_pdf = staging / f".{base_name}.generated.pdf"
        export_pdf_with_word(new_word, generated_pdf)
        if source_word.name != new_word.name:
            (staging / source_word.name).unlink()
        if issued_item and source_pdf and source_pdf.name != new_pdf.name:
            (staging / source_pdf.name).unlink()
        previous_attachment_files = [
            item for item in record.get("files") or []
            if item.get("role") in {"attachment_word", "attachment_pdf"}
            and str(item.get("name") or "").startswith(
                f"附件（{record['document_code']}）_"
            )
        ]
        for item in previous_attachment_files:
            old_attachment = staging / str(item["name"])
            if old_attachment.is_file():
                old_attachment.unlink()
        if values["attachment_content"]:
            attachment_base = _attachment_name(code, values["subject"])
            attachment_word = staging / f"{attachment_base}.docx"
            attachment_pdf = staging / f"{attachment_base}.pdf"
            write_attachment_docx(
                attachment_word, subject=values["subject"],
                content=values["attachment_content"],
            )
            export_pdf_with_word(attachment_word, attachment_pdf)
        else:
            attachment_word = attachment_pdf = None
        pages = assemble_work_contact_pdf(
            generated_pdf, new_pdf, attachment=attachment_pdf, previous=source_pdf,
            previous_attachment_pages=(
                previous_metadata[1] if previous_metadata and issued_item else 0
            ),
        )
        generated_pdf.unlink()
        if attachment_word and attachment_pdf:
            write_attachment_metadata(staging, values["attachment_content"], pages)
            attachment_word.unlink()
            attachment_pdf.unlink()
        else:
            (staging / METADATA_NAME).unlink(missing_ok=True)
        source_dir.replace(snapshot)
        try:
            for name in (JSON_NAME, "主体工作联系单汇总.html"):
                original = root / name
                if original.is_file():
                    shutil.copy2(original, snapshot / f"更新前_{name}")
            staging.replace(target_dir)
            result = build_work_contact_archive(root)
            if result["records"] != len(data.get("records") or []):
                raise ValueError("更新后联系单记录数不一致")
        except Exception:
            if target_dir.exists() and not staging.exists():
                target_dir.replace(staging)
            for name in (JSON_NAME, "主体工作联系单汇总.html"):
                saved = snapshot / f"更新前_{name}"
                if saved.is_file():
                    shutil.copy2(saved, root / name)
                    saved.unlink()
            if not source_dir.exists():
                snapshot.replace(source_dir)
            raise
        refreshed = json.loads((root / JSON_NAME).read_text(encoding="utf-8"))
        return {
            "ok": True,
            "changed": True,
            "folder_path": target_dir.name,
            "previous_version": snapshot.relative_to(root).as_posix(),
            "dataset_revision": refreshed["dataset_revision"],
        }
