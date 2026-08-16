"""基于既有工作联系单 DOCX 模板定点生成新联系单。"""

from __future__ import annotations

import copy
import io
import re
import tempfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from .docx_parser import parse_docx


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
ET.register_namespace("w", W_NS)


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{W}t"))


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value)


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


def _replace_content(document: ET.Element, value: str) -> None:
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
    for paragraph in candidates:
        parent.remove(paragraph)
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n") or [""]
    for offset, line in enumerate(lines):
        paragraph = copy.deepcopy(prototype)
        _set_paragraph_text(paragraph, line)
        parent.insert(insertion_index + offset, paragraph)


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
            _replace_after_colon(recipient_paragraph, recipient)
            _replace_after_colon(subject_paragraph, subject)
            _replace_content(document, requirement_content)
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
