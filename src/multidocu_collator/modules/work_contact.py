"""扫描平铺存放的主体工作联系单，不修改原始资料。"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .docx_parser import W, parse_docx
from .file_utils import relative_posix, sha256_file


DOCUMENT_NAME = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_工作联系单_(?P<subject>.+)\.docx$")


def _body_text(path: Path) -> str:
    """主体版式正文没有统一下划线，读取“内容”到落款之间的有效文字。"""
    try:
        with ZipFile(path) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError(f"无法读取 DOCX: {path.name}: {exc}") from exc
    paragraphs = [
        "".join(node.text or "" for node in paragraph.iter(f"{W}t")).strip()
        for paragraph in document.iter(f"{W}p")
    ]
    start = next(
        (index for index, line in enumerate(paragraphs) if re.match(r"^内\s*容\s*[：:]", line)),
        None,
    )
    if start is None:
        return ""
    first = re.sub(r"^内\s*容\s*[：:]", "", paragraphs[start]).strip()
    content = [first] if first else []
    for line in paragraphs[start + 1 :]:
        if re.match(r"^(抄\s*送|部门负责人|总包签收|签收|备注)\s*[：:]?", line):
            break
        if line:
            content.append(line)
    return "\n".join(content).strip()


def _file_item(path: Path, root: Path, role: str) -> dict[str, Any]:
    return {
        "path": relative_posix(path, root),
        "name": path.name,
        "role": role,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def scan_work_contacts(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """每个根目录 DOCX 作为一条记录；同名 PDF 和扫描件归到该记录。"""
    if not root.is_dir():
        raise FileNotFoundError(f"主体工作联系单目录不存在: {root}")
    records: list[dict[str, Any]] = []
    matched_files: set[Path] = set()
    words = sorted(root.glob("*.docx"), key=lambda path: path.name)
    normal_stems = {path.stem for path in words if not path.stem.endswith(" - 副本")}
    for word in words:
        match = DOCUMENT_NAME.match(word.name)
        if not match:
            continue
        if word.stem.endswith(" - 副本") and word.stem.removesuffix(" - 副本") in normal_stems:
            continue
        warnings: list[str] = []
        try:
            fields = parse_docx(word)
            content = _body_text(word)
        except (OSError, ValueError) as exc:
            fields = None
            content = ""
            warnings.append(f"Word 读取失败：{type(exc).__name__}")
        if fields and fields.document_date and fields.document_date != match["date"]:
            warnings.append("Word 日期与文件名不一致")
        if not content:
            warnings.append("未提取到正文内容")
        files = []
        candidates = [(word, "source_word")]
        for suffix, role in (("", "issued_pdf"), ("_扫描件", "signed_scan")):
            pdf = root / f"{word.stem}{suffix}.pdf"
            if pdf.is_file():
                candidates.append((pdf, role))
        for path, role in candidates:
            try:
                files.append(_file_item(path, root, role))
                matched_files.add(path)
            except OSError as exc:
                warnings.append(f"资料文件读取失败：{path.name}（{type(exc).__name__}）")
        if not any(item["role"] in {"issued_pdf", "signed_scan"} for item in files):
            warnings.append("缺少联系单 PDF 或扫描件")
        records.append({
            "record_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"structural-work-contact:{word.name}")),
            "folder_date": match["date"],
            "document_code": fields.document_no if fields else "",
            "subject": match["subject"].strip(),
            "致送单位": fields.recipient if fields else "",
            "内容": content,
            "word_subject": fields.subject if fields else "",
            "files": files,
            "status": "needs_review" if any("不一致" in item or "读取失败" in item for item in warnings) else (
                "complete" if any(item["role"] in {"issued_pdf", "signed_scan"} for item in files) else "incomplete"
            ),
            "warnings": warnings,
        })
    records.sort(key=lambda row: (row["folder_date"], row["subject"]))
    unmatched = [
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and path not in matched_files
        and path.name not in {"主体工作联系单数据.json", "主体工作联系单汇总.html"}
        and not path.name.startswith("~$")
    ]
    return records, unmatched
