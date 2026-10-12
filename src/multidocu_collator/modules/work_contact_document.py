"""在主体工作联系单版式中定点更新业务字段。"""

from __future__ import annotations

import copy
import re
import tempfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from .docx_parser import parse_docx
from .document_generator import (
    W,
    _normalized,
    _paragraph_after_label,
    _paragraph_text,
    _parse_preserving_namespaces,
    _serialize_preserving_root,
    _set_paragraph_text,
)
from .work_contact import BODY_END, _body_text


def _replace_field(paragraph: ET.Element, value: str) -> None:
    nodes = list(paragraph.iter(f"{W}t"))
    original = [node.text or "" for node in nodes]
    combined = "".join(original)
    marker = re.search(r"[：:]", combined)
    if marker is None:
        raise ValueError("主体联系单字段缺少冒号")
    boundary = marker.end()
    position = 0
    written = False
    for node, text in zip(nodes, original):
        end = position + len(text)
        if end > boundary:
            prefix = text[: max(0, boundary - position)]
            node.text = prefix + (value if not written else "")
            written = True
        position = end
    if not written:
        # 标签后的值可能在独立 run 中，但原模板对应文字为空。
        if not nodes:
            raise ValueError("主体联系单字段缺少文字节点")
        nodes[-1].text = (nodes[-1].text or "") + value


def _replace_body(document: ET.Element, content: str) -> None:
    paragraphs = list(document.iter(f"{W}p"))
    labels = [
        index for index, paragraph in enumerate(paragraphs)
        if re.match(r"^内\s*容\s*[：:]", _paragraph_text(paragraph).strip())
    ]
    if not labels or labels != list(range(labels[0], labels[-1] + 1)):
        raise ValueError("主体联系单应包含连续的“内容：”段落")
    start = labels[-1]
    end = next(
        (index for index in range(start + 1, len(paragraphs))
         if BODY_END.match(_paragraph_text(paragraphs[index]).strip())),
        None,
    )
    if end is None or end <= start + 1:
        raise ValueError("主体联系单缺少正文结束标记")
    candidates = paragraphs[start + 1 : end]
    parent_map = {child: parent for parent in document.iter() for child in parent}
    parent = parent_map[candidates[0]]
    if any(parent_map[item] is not parent for item in candidates):
        raise ValueError("主体联系单正文跨越多个表格单元，无法安全更新")
    if any(paragraph.find(f".//{W}drawing") is not None for paragraph in candidates):
        raise ValueError("正文包含内嵌图形，请在 Word 中人工修改")
    prototype = copy.deepcopy(next(
        (paragraph for paragraph in candidates if _paragraph_text(paragraph).strip()),
        candidates[0],
    ))
    insertion = list(parent).index(candidates[0])
    for paragraph in candidates:
        parent.remove(paragraph)
    for offset, line in enumerate(content.splitlines() or [""]):
        paragraph = copy.deepcopy(prototype)
        _set_paragraph_text(paragraph, line)
        parent.insert(insertion + offset, paragraph)


def write_work_contact_docx(
    source: Path,
    output: Path,
    *,
    document_no: str,
    document_date: date,
    recipient: str,
    subject: str,
    content: str,
) -> Path:
    """保留 DOCX 其余包成员，生成后回读关键业务字段。"""
    with ZipFile(source) as archive:
        original_xml = archive.read("word/document.xml")
        document = _parse_preserving_namespaces(original_xml)
        paragraphs = list(document.iter(f"{W}p"))
        _set_paragraph_text(_paragraph_after_label(paragraphs, "资料编号"), document_no)
        _set_paragraph_text(
            _paragraph_after_label(paragraphs, "日期"),
            f"{document_date.year}年{document_date.month}月{document_date.day}日",
        )
        recipient_paragraph = next(
            paragraph for paragraph in paragraphs
            if _normalized(_paragraph_text(paragraph)).startswith("致(单位)：")
        )
        subject_paragraph = next(
            paragraph for paragraph in paragraphs
            if _normalized(_paragraph_text(paragraph)).startswith("事由：")
        )
        _replace_field(recipient_paragraph, recipient)
        _replace_field(subject_paragraph, subject)
        _replace_body(document, content)
        updated_xml = _serialize_preserving_root(document, original_xml)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
        try:
            with ZipFile(temporary, "w", ZIP_DEFLATED) as target:
                for info in archive.infolist():
                    target.writestr(
                        info,
                        updated_xml if info.filename == "word/document.xml" else archive.read(info),
                    )
            temporary.replace(output)
        finally:
            if temporary.exists():
                temporary.unlink()
    parsed = parse_docx(output)
    if parsed.document_date != document_date.isoformat() or parsed.recipient != recipient or parsed.subject != subject:
        raise ValueError("主体联系单生成后字段回读校验失败")
    if _body_text(output) != content.strip():
        raise ValueError("主体联系单生成后正文回读校验失败")
    return output
