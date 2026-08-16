"""从 DOCX 当前有效文字中提取联系单字段。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"


@dataclass(frozen=True)
class DocxFields:
    document_no: str = ""
    document_date: str = ""
    project_name: str = ""
    recipient: str = ""
    subject: str = ""
    requirement_content: str = ""


def _is_underlined(run: ET.Element) -> bool:
    properties = run.find(f"{W}rPr")
    underline = properties.find(f"{W}u") if properties is not None else None
    if underline is None:
        return False
    value = underline.get(f"{W}val", "single").lower()
    return value not in {"none", "0", "false"}


def _annotated_characters(document: ET.Element) -> list[tuple[str, bool]]:
    annotated: list[tuple[str, bool]] = []
    paragraphs = list(document.iter(f"{W}p"))
    for paragraph_index, paragraph in enumerate(paragraphs):
        for run in paragraph.iter(f"{W}r"):
            underlined = _is_underlined(run)
            for node in run.iter():
                if node.tag == f"{W}t":
                    annotated.extend((char, underlined) for char in (node.text or ""))
                elif node.tag == f"{W}tab":
                    annotated.append(("\t", underlined))
                elif node.tag in {f"{W}br", f"{W}cr"}:
                    annotated.append(("\n", underlined))
        if paragraph_index < len(paragraphs) - 1:
            annotated.append(("\n", False))
    return annotated


def _current_text(annotated: list[tuple[str, bool]]) -> str:
    return "".join(char for char, _ in annotated)


def _extract(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.DOTALL)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _extract_requirement_content(annotated: list[tuple[str, bool]]) -> str:
    text = _current_text(annotated)
    start_match = re.search(r"内容\s*[：:]", text)
    if not start_match:
        return ""
    end_match = re.search(r"备注\s*[：:]", text[start_match.end() :])
    end = (
        start_match.end() + end_match.start()
        if end_match
        else len(annotated)
    )
    selected: list[str] = []
    for char, underlined in annotated[start_match.end() : end]:
        if underlined:
            selected.append(char)
        elif char == "\n" and selected and selected[-1] != "\n":
            selected.append("\n")
    value = "".join(selected)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def parse_docx(path: Path) -> DocxFields:
    try:
        with ZipFile(path) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError(f"无法读取 DOCX: {path.name}: {exc}") from exc

    annotated = _annotated_characters(document)
    text = _current_text(annotated)
    date_match = re.search(
        r"日\s*期\s*(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text
    )
    document_date = ""
    if date_match:
        document_date = (
            f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-"
            f"{int(date_match.group(3)):02d}"
        )
    return DocxFields(
        document_no=_extract(r"资料编号\s*(.+?)\s*工程名称", text),
        document_date=document_date,
        project_name=_extract(r"工程名称\s*(.+?)\s*日\s*期", text),
        recipient=_extract(r"致\s*\(单位\)\s*[：:]\s*(.+?)\s*事由\s*[：:]", text),
        subject=_extract(r"事由\s*[：:]\s*(.+?)\s*内容\s*[：:]", text),
        requirement_content=_extract_requirement_content(annotated),
    )
