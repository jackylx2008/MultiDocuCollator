"""基于既有工作联系单 DOCX 模板定点生成新联系单。"""

from __future__ import annotations

import copy
import io
import re
import tempfile
import unicodedata
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from .docx_parser import parse_docx


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
ET.register_namespace("w", W_NS)

# 正文原型约可容纳 45 个全角字符；用半角宽度单位估算 Word 自动换行数。
CONTENT_LINE_CAPACITY = 90
BODY_LINE_HEIGHT_TWIPS = 240


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{W}t"))


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _estimated_visual_lines(value: str) -> int:
    units = sum(
        2 if unicodedata.east_asian_width(character) in "WFA" else 1
        for character in value
    )
    return max(1, (units + CONTENT_LINE_CAPACITY - 1) // CONTENT_LINE_CAPACITY)


def _parse_preserving_namespaces(xml: bytes) -> ET.Element:
    for _, pair in ET.iterparse(io.BytesIO(xml), events=("start-ns",)):
        prefix, namespace = pair
        if not prefix.startswith("ns"):
            ET.register_namespace(prefix, namespace)
    return ET.fromstring(xml)


def _serialize_preserving_root(document: ET.Element, original: bytes) -> bytes:
    """保留 Word 根节点中 mc:Ignorable 依赖的未使用命名空间声明。"""
    generated = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    original_match = re.search(br"<w:document\b[^>]*>", original)
    generated_match = re.search(br"<w:document\b[^>]*>", generated)
    if not original_match or not generated_match:
        raise ValueError("模板 document.xml 根节点异常")
    return (
        generated[: generated_match.start()]
        + original_match.group(0)
        + generated[generated_match.end() :]
    )


def _set_paragraph_text(paragraph: ET.Element, value: str) -> None:
    nodes = list(paragraph.iter(f"{W}t"))
    if not nodes:
        raise ValueError("模板目标段落没有可替换文字节点")
    nodes[0].text = value
    if value.startswith(" ") or value.endswith(" "):
        nodes[0].set(XML_SPACE, "preserve")
    for node in nodes[1:]:
        node.text = ""


def _paragraph_after_label(paragraphs: list[ET.Element], label: str) -> ET.Element:
    wanted = _normalized(label)
    for index, paragraph in enumerate(paragraphs[:-1]):
        if _normalized(_paragraph_text(paragraph)) == wanted:
            return paragraphs[index + 1]
    raise ValueError(f"模板缺少“{label}”字段")


def _replace_after_colon(paragraph: ET.Element, value: str) -> None:
    nodes = list(paragraph.iter(f"{W}t"))
    texts = [node.text or "" for node in nodes]
    combined = "".join(texts)
    marker = max(combined.find("："), combined.find(":"))
    if marker < 0:
        raise ValueError("模板字段缺少冒号")
    boundary = marker + 1
    cursor = 0
    written = False
    for node, original in zip(nodes, texts):
        end = cursor + len(original)
        if end <= boundary:
            cursor = end
            continue
        prefix_length = max(0, boundary - cursor)
        prefix = original[:prefix_length]
        node.text = prefix + (value if not written else "")
        written = True
        cursor = end
    if not written:
        raise ValueError("模板字段冒号后没有可替换文字节点")


def _replace_content(document: ET.Element, value: str) -> int:
    paragraphs = list(document.iter(f"{W}p"))
    content_index = next(
        (i for i, p in enumerate(paragraphs) if _normalized(_paragraph_text(p)) == "内容："),
        None,
    )
    remark_index = next(
        (
            i
            for i, p in enumerate(paragraphs)
            if _normalized(_paragraph_text(p)).startswith("备注：")
        ),
        None,
    )
    if content_index is None or remark_index is None or remark_index <= content_index + 1:
        raise ValueError("模板缺少可替换的内容正文区")
    candidates = paragraphs[content_index + 1 : remark_index]
    parent_map = {child: parent for parent in document.iter() for child in parent}
    parent = parent_map[candidates[0]]
    if parent_map[paragraphs[remark_index]] is not parent or any(
        parent_map[item] is not parent for item in candidates
    ):
        raise ValueError("模板内容正文区结构不符合预期")
    insertion_index = list(parent).index(candidates[0])
    prototype = copy.deepcopy(candidates[0])
    original_line_count = sum(
        _estimated_visual_lines(_paragraph_text(paragraph)) for paragraph in candidates
    )
    for paragraph in candidates:
        parent.remove(paragraph)
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n") or [""]
    for offset, line in enumerate(lines):
        paragraph = copy.deepcopy(prototype)
        _set_paragraph_text(paragraph, line)
        parent.insert(insertion_index + offset, paragraph)
    new_line_count = sum(_estimated_visual_lines(line) for line in lines)
    return new_line_count - original_line_count


def _resize_filler_paragraphs(document: ET.Element, line_delta: int) -> int:
    """按可变内容的换行增量调整“以下空白”后的空段落数量。"""
    paragraphs = list(document.iter(f"{W}p"))
    blank_marker_index = next(
        (
            index
            for index, paragraph in enumerate(paragraphs)
            if _normalized(_paragraph_text(paragraph)) == "以下空白"
        ),
        None,
    )
    if blank_marker_index is None:
        return 0
    copy_index = next(
        (
            index
            for index in range(blank_marker_index + 1, len(paragraphs))
            if _normalized(_paragraph_text(paragraphs[index])).startswith("抄送")
        ),
        None,
    )
    if copy_index is None:
        return 0
    parent_map = {child: parent for parent in document.iter() for child in parent}
    marker = paragraphs[blank_marker_index]
    copy_paragraph = paragraphs[copy_index]
    parent = parent_map.get(marker)
    if parent is None or parent_map.get(copy_paragraph) is not parent:
        return 0
    fillers = [
        paragraph
        for paragraph in paragraphs[blank_marker_index + 1 : copy_index]
        if parent_map.get(paragraph) is parent and not _normalized(_paragraph_text(paragraph))
    ]
    if not fillers:
        return max(0, line_delta)
    target_count = max(0, len(fillers) - line_delta)
    if target_count < len(fillers):
        for paragraph in fillers[target_count:]:
            parent.remove(paragraph)
    elif target_count > len(fillers):
        prototype = copy.deepcopy(fillers[-1])
        insertion_index = list(parent).index(copy_paragraph)
        for offset in range(target_count - len(fillers)):
            parent.insert(insertion_index + offset, copy.deepcopy(prototype))
    return max(0, line_delta - len(fillers))


def _shrink_body_row_minimum(document: ET.Element, overflow_lines: int) -> None:
    """正文超过可回收空白时，缩减外层表格行的最小高度以避免空白尾页。"""
    if overflow_lines <= 0:
        return
    paragraphs = list(document.iter(f"{W}p"))
    marker = next(
        (
            paragraph
            for paragraph in paragraphs
            if _normalized(_paragraph_text(paragraph)) == "以下空白"
        ),
        None,
    )
    if marker is None:
        return
    parent_map = {child: parent for parent in document.iter() for child in parent}
    cell = parent_map.get(marker)
    row = parent_map.get(cell) if cell is not None else None
    if row is None or row.tag != f"{W}tr":
        return
    height = row.find(f"{W}trPr/{W}trHeight")
    if height is None:
        return
    try:
        current = int(height.get(f"{W}val") or "0")
    except ValueError:
        return
    height.set(
        f"{W}val",
        str(max(BODY_LINE_HEIGHT_TWIPS, current - overflow_lines * BODY_LINE_HEIGHT_TWIPS)),
    )


def generate_contact_docx(
    template: Path,
    output: Path,
    *,
    document_no: str,
    document_date: date,
    recipient: str,
    subject: str,
    requirement_content: str,
) -> Path:
    """复制模板并替换业务字段；未修改的 DOCX 包成员保持原字节。"""
    if not template.is_file():
        raise FileNotFoundError(f"联系单模板不存在: {template}")
    try:
        with ZipFile(template) as source:
            original_document_xml = source.read("word/document.xml")
            document = _parse_preserving_namespaces(original_document_xml)
            paragraphs = list(document.iter(f"{W}p"))
            _set_paragraph_text(_paragraph_after_label(paragraphs, "资料编号"), document_no)
            _set_paragraph_text(
                _paragraph_after_label(paragraphs, "日期"),
                f"{document_date.year}年{document_date.month}月{document_date.day}日",
            )
            recipient_paragraph = next(
                p for p in paragraphs if _normalized(_paragraph_text(p)).startswith("致(单位)：")
            )
            subject_paragraph = next(
                p for p in paragraphs if _normalized(_paragraph_text(p)).startswith("事由：")
            )
            original_recipient_lines = _estimated_visual_lines(
                _paragraph_text(recipient_paragraph)
            )
            original_subject_lines = _estimated_visual_lines(
                _paragraph_text(subject_paragraph)
            )
            _replace_after_colon(recipient_paragraph, recipient)
            _replace_after_colon(subject_paragraph, subject)
            variable_line_delta = (
                _estimated_visual_lines(_paragraph_text(recipient_paragraph))
                - original_recipient_lines
                + _estimated_visual_lines(_paragraph_text(subject_paragraph))
                - original_subject_lines
            )
            variable_line_delta += _replace_content(document, requirement_content)
            overflow_lines = _resize_filler_paragraphs(document, variable_line_delta)
            _shrink_body_row_minimum(document, overflow_lines)
            document_xml = _serialize_preserving_root(document, original_document_xml)
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
            try:
                with ZipFile(temporary, "w", ZIP_DEFLATED) as target:
                    for info in source.infolist():
                        target.writestr(
                            info,
                            document_xml
                            if info.filename == "word/document.xml"
                            else source.read(info),
                        )
                temporary.replace(output)
            finally:
                if temporary.exists():
                    temporary.unlink()
    except (BadZipFile, KeyError, ET.ParseError, StopIteration) as exc:
        raise ValueError(f"无法使用联系单模板: {exc}") from exc

    parsed = parse_docx(output)
    expected = {
        "资料编号": (parsed.document_no, document_no),
        "日期": (parsed.document_date, document_date.isoformat()),
        "致送单位": (parsed.recipient, recipient),
        "事由": (parsed.subject, subject),
        "需求内容": (parsed.requirement_content, requirement_content.strip()),
    }
    mismatches = [name for name, (actual, wanted) in expected.items() if actual != wanted]
    if mismatches:
        raise ValueError("生成的 DOCX 字段校验失败: " + "、".join(mismatches))
    return output


def update_contact_content(
    source_path: Path,
    output: Path,
    *,
    requirement_content: str,
    subject: str | None = None,
) -> Path:
    """替换既有联系单的主题/需求正文，其他业务字段和 DOCX 部件保持不变。"""
    if not source_path.is_file():
        raise FileNotFoundError(f"联系单 Word 不存在: {source_path}")
    original_fields = parse_docx(source_path)
    try:
        with ZipFile(source_path) as source:
            original_document_xml = source.read("word/document.xml")
            document = _parse_preserving_namespaces(original_document_xml)
            line_delta = 0
            if subject is not None:
                paragraphs = list(document.iter(f"{W}p"))
                subject_paragraph = next(
                    p
                    for p in paragraphs
                    if _normalized(_paragraph_text(p)).startswith("事由：")
                )
                original_subject_lines = _estimated_visual_lines(
                    _paragraph_text(subject_paragraph)
                )
                _replace_after_colon(subject_paragraph, subject)
                line_delta += (
                    _estimated_visual_lines(_paragraph_text(subject_paragraph))
                    - original_subject_lines
                )
            line_delta += _replace_content(document, requirement_content)
            overflow_lines = _resize_filler_paragraphs(document, line_delta)
            _shrink_body_row_minimum(document, overflow_lines)
            document_xml = _serialize_preserving_root(document, original_document_xml)
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix=f".{output.name}.",
                suffix=".tmp",
                dir=output.parent,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
            try:
                with ZipFile(temporary, "w", ZIP_DEFLATED) as target:
                    for info in source.infolist():
                        target.writestr(
                            info,
                            document_xml
                            if info.filename == "word/document.xml"
                            else source.read(info),
                        )
                temporary.replace(output)
            finally:
                if temporary.exists():
                    temporary.unlink()
    except (BadZipFile, KeyError, ET.ParseError, StopIteration) as exc:
        raise ValueError(f"无法更新联系单 Word: {exc}") from exc

    updated_fields = parse_docx(output)
    unchanged = {
        "资料编号": (updated_fields.document_no, original_fields.document_no),
        "日期": (updated_fields.document_date, original_fields.document_date),
        "致送单位": (updated_fields.recipient, original_fields.recipient),
        "事由": (
            updated_fields.subject,
            original_fields.subject if subject is None else subject,
        ),
        "工程名称": (updated_fields.project_name, original_fields.project_name),
    }
    changed_fields = [
        name for name, (actual, original) in unchanged.items() if actual != original
    ]
    if changed_fields:
        raise ValueError("更新 DOCX 时意外修改了字段: " + "、".join(changed_fields))
    if updated_fields.requirement_content != requirement_content.strip():
        raise ValueError("更新后的 DOCX 需求内容回读校验失败")
    return output
