"""资料目录扫描、文件分类和记录构建。"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .docx_parser import DocxFields, parse_docx
from .file_utils import relative_posix, sha256_file


FOLDER_PATTERN = re.compile(
    r"^(?P<discipline>.+)-(?P<sequence>\d+)-"
    r"(?P<date>\d{4}-\d{2}-\d{2})_(?P<subject>.+)$"
)
IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def _file_role(path: Path) -> str:
    suffix = path.suffix.lower()
    name = path.stem
    if suffix == ".docx":
        return "source_word"
    if suffix == ".pdf":
        if "扫描件" in name:
            return "signed_scan"
        if name.startswith("需求工作联系单"):
            return "issued_pdf"
        return "attachment_pdf"
    if suffix in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic"}:
        return "image_attachment"
    if suffix in {".dwg", ".dxf"}:
        return "drawing_source"
    return "auxiliary_file"


def _file_item(path: Path, root: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": relative_posix(path, root),
        "name": path.name,
        "extension": path.suffix.lower(),
        "role": _file_role(path),
        "size": stat.st_size,
        "sha256": sha256_file(path),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(
            timespec="seconds"
        ),
        "exists": True,
    }


def _choose_word(
    words: list[Path], expected_code: str
) -> tuple[Path | None, DocxFields, list[str]]:
    warnings: list[str] = []
    parsed: list[tuple[Path, DocxFields]] = []
    for word in words:
        try:
            parsed.append((word, parse_docx(word)))
        except PermissionError:
            warnings.append(f"无法读取 Word 文件“{word.name}”：没有读取权限")
        except OSError as exc:
            warnings.append(
                f"无法读取 Word 文件“{word.name}”：{type(exc).__name__}"
            )
        except ValueError as exc:
            warnings.append(str(exc))
    matching = [item for item in parsed if item[1].document_no == expected_code]
    selected = matching[0] if matching else (parsed[0] if parsed else None)
    if not words:
        warnings.append("缺少 Word 联系单")
    elif len(words) > 1:
        warnings.append(f"存在 {len(words)} 个 Word 文件，已按资料编号优先选择")
    if selected is None:
        return None, DocxFields(), warnings
    return selected[0], selected[1], warnings


def _record(directory: Path, root: Path, match: re.Match[str]) -> dict[str, Any]:
    discipline = match.group("discipline")
    sequence = match.group("sequence")
    folder_date = match.group("date")
    subject = match.group("subject")
    expected_code = f"{discipline}-{sequence}"
    files = [
        path
        for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and path.name not in IGNORED_NAMES and not path.name.startswith("~$")
    ]
    words = [path for path in files if path.suffix.lower() == ".docx"]
    selected_word, word, warnings = _choose_word(words, expected_code)
    file_items: list[dict[str, Any]] = []
    for path in files:
        try:
            file_items.append(_file_item(path, root))
        except PermissionError:
            warnings.append(
                f"资料文件“{relative_posix(path, root)}”没有读取权限，已跳过"
            )
        except OSError as exc:
            warnings.append(
                f"资料文件“{relative_posix(path, root)}”读取失败，已跳过"
                f"（{type(exc).__name__}）"
            )
    if word.document_no and word.document_no != expected_code:
        warnings.append(
            f"资料编号不一致：目录为“{expected_code}”，Word 为“{word.document_no}”"
        )
    if word.document_date and word.document_date != folder_date:
        warnings.append(
            f"日期不一致：目录为“{folder_date}”，Word 为“{word.document_date}”"
        )
    if word.subject and word.subject != subject:
        warnings.append(
            f"主题不一致：目录为“{subject}”，Word 为“{word.subject}”"
        )
    roles = [str(item["role"]) for item in file_items]
    if "issued_pdf" not in roles and "signed_scan" not in roles:
        warnings.append("缺少联系单 PDF 或扫描件")
    if not word.requirement_content:
        warnings.append("未提取到“内容：”后的下划线需求内容")

    key = f"hotel-requirement:{discipline}:{sequence}"
    if any("不一致" in warning for warning in warnings):
        status = "needs_review"
    elif selected_word and ("issued_pdf" in roles or "signed_scan" in roles):
        status = "complete"
    else:
        status = "incomplete"
    return {
        "record_id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)),
        "discipline": discipline,
        "sequence_no": sequence,
        "document_code": expected_code,
        "folder_date": folder_date,
        "subject": subject,
        "致送单位": word.recipient,
        "需求内容": word.requirement_content,
        "folder_path": relative_posix(directory, root),
        "word_fields": {
            "source_path": relative_posix(selected_word, root) if selected_word else "",
            "document_no": word.document_no,
            "document_date": word.document_date,
            "project_name": word.project_name,
            "recipient": word.recipient,
            "subject": word.subject,
        },
        "files": file_items,
        "status": status,
        "warnings": warnings,
    }


def scan_data_root(
    root: Path, *, generated_names: set[str] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[str]]:
    records: list[dict[str, Any]] = []
    unmatched: list[dict[str, str]] = []
    ignored: list[str] = []
    excluded = generated_names or set()
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.name in IGNORED_NAMES or path.name.startswith("~$"):
            ignored.append(path.name)
            continue
        if path.name in excluded:
            ignored.append(path.name)
            continue
        if path.is_file():
            unmatched.append({"path": path.name, "reason": "资料根目录中的非成果文件"})
            continue
        if not path.is_dir():
            continue
        match = FOLDER_PATTERN.match(path.name)
        if not match:
            unmatched.append({"path": path.name, "reason": "一级目录名称不符合规则"})
            continue
        records.append(_record(path, root, match))
    records.sort(
        key=lambda item: (
            item["folder_date"],
            item["discipline"],
            int(item["sequence_no"]),
        )
    )
    return records, unmatched, ignored
