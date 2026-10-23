"""生成和读取主体工作联系单的独立问题附件。"""

from __future__ import annotations

import json
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


TITLE = "附件：具体问题及整改要求"
METADATA_NAME = ".work_contact_attachment.json"


def read_attachment_metadata(directory: Path) -> tuple[str, int] | None:
    path = directory / METADATA_NAME
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    content, pages = data.get("content"), data.get("pages")
    if not isinstance(content, str) or not isinstance(pages, int) or pages < 1:
        raise ValueError("附件元数据格式不正确")
    return content, pages


def write_attachment_metadata(directory: Path, content: str, pages: int) -> None:
    if not content or pages < 1:
        raise ValueError("附件元数据内容或页数无效")
    (directory / METADATA_NAME).write_text(
        json.dumps({"content": content, "pages": pages}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_attachment_docx(output: Path, *, subject: str, content: str) -> Path:
    document = Document()
    section = document.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2.4)
    section.left_margin = section.right_margin = Cm(2.6)

    normal = document.styles["Normal"]
    normal.font.name = "宋体"
    normal.font.size = Pt(12)
    normal.font.color.rgb = RGBColor(0, 0, 0)
    normal._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "宋体")
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(6)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(14)
    run = title.add_run(TITLE)
    run.bold = True
    run.font.name = "黑体"
    run.font.size = Pt(16)
    run.font.color.rgb = RGBColor(0, 0, 0)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "黑体")

    heading = document.add_paragraph()
    heading.add_run(f"对应事由：{subject}")
    heading.paragraph_format.space_after = Pt(12)
    for line in content.split("\n"):
        document.add_paragraph(line)
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)
    if read_attachment_docx(output) != content:
        raise ValueError("附件 Word 生成后正文回读校验失败")
    return output


def read_attachment_docx(path: Path) -> str:
    paragraphs = Document(path).paragraphs
    if len(paragraphs) < 3 or paragraphs[0].text.strip() != TITLE:
        raise ValueError("附件 Word 缺少预期标题或内容")
    return "\n".join(paragraph.text for paragraph in paragraphs[2:]).strip()
