"""面试方案导出：把 Markdown 正文转换为 Markdown 文件或 Word 文档。

导出逻辑独立于接口与数据库，便于单测。Word 转换只覆盖面试方案常见的 Markdown
结构（标题、列表、引用、表格、代码块与加粗），不追求完整的 Markdown 渲染能力。
"""

from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO
from urllib.parse import quote

from app.db.models import InterviewPlan
from app.schemas.interview_plan import ExportFormat

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ILLEGAL_FILENAME = re.compile(r'[\\/:*?"<>|\r\n]+')
_FENCE = re.compile(r"^\s*```")
_RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$")

_EXPORT_EXTENSIONS = {
    ExportFormat.DOCX: "docx",
    ExportFormat.MARKDOWN: "md",
}


def _clean_filename_part(value: str, fallback: str, max_length: int = 40) -> str:
    cleaned = _ILLEGAL_FILENAME.sub("_", value).strip(" ._")
    return (cleaned or fallback)[:max_length]


def build_filename(plan: InterviewPlan, export_format: ExportFormat) -> str:
    """生成带候选人姓名与日期的导出文件名。"""
    candidate = _clean_filename_part(plan.candidate_name, "候选人")
    created = plan.created_at or datetime.now()
    extension = _EXPORT_EXTENSIONS[export_format]
    return f"面试方案-{candidate}-{created:%Y%m%d}.{extension}"


def content_disposition(filename: str) -> str:
    """构造兼容中文文件名的 ``Content-Disposition`` 响应头。"""
    extension = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    fallback = f"interview-plan.{extension}"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


def build_markdown(plan: InterviewPlan) -> str:
    """导出为 Markdown：附带候选人、岗位与关联 JD 信息。"""
    lines = [
        f"# {plan.candidate_name} 面试方案",
        "",
        f"- 应聘岗位：{plan.candidate_position}",
    ]
    if plan.job_title:
        lines.append(f"- 关联 JD：{plan.job_title}")
    lines.extend(["", "---", "", plan.content.strip(), ""])
    return "\n".join(lines)


def _add_inline_runs(paragraph: object, text: str) -> None:
    """写入一行文本，并把 ``**加粗**`` / 行内代码转换为 Word run。"""
    # python-docx 的 Paragraph 类型仅在函数内导入，避免模块导入时依赖具体类型
    from docx.shared import Pt

    plain = _INLINE_CODE.sub(r"\1", text)
    position = 0
    for match in _BOLD.finditer(plain):
        if match.start() > position:
            paragraph.add_run(plain[position : match.start()])  # type: ignore[attr-defined]
        run = paragraph.add_run(match.group(1))  # type: ignore[attr-defined]
        run.bold = True
        position = match.end()
    if position < len(plain):
        paragraph.add_run(plain[position:])  # type: ignore[attr-defined]

    for run in paragraph.runs:  # type: ignore[attr-defined]
        run.font.size = Pt(10.5)


def _configure_document(document: object) -> None:
    """设置中文字体与正文样式。"""
    from docx.oxml.ns import qn
    from docx.shared import Pt

    normal = document.styles["Normal"]  # type: ignore[attr-defined]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(10.5)
    rpr = normal.element.get_or_add_rPr()
    rpr.get_or_add_rFonts().set(qn("w:eastAsia"), "微软雅黑")


def _parse_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    header = lines[index].strip()
    separator = lines[index + 1].strip()
    return (
        header.startswith("|") and header.endswith("|") and bool(_TABLE_SEPARATOR.match(separator))
    )


def _add_table(document: object, lines: list[str], start: int) -> int:
    """把连续 Markdown 表格行转换成 Word 表格，返回表格后的行号。"""
    header = _parse_table_row(lines[start])
    rows: list[list[str]] = []
    index = start + 2
    while index < len(lines) and lines[index].strip().startswith("|"):
        rows.append(_parse_table_row(lines[index]))
        index += 1

    columns = max([len(header), *(len(row) for row in rows)])
    table = document.add_table(rows=1, cols=columns)  # type: ignore[attr-defined]
    table.style = "Table Grid"
    for cell_index in range(columns):
        paragraph = table.rows[0].cells[cell_index].paragraphs[0]
        _add_inline_runs(paragraph, header[cell_index] if cell_index < len(header) else "")
        for run in paragraph.runs:
            run.bold = True

    for row in rows:
        cells = table.add_row().cells
        for cell_index in range(columns):
            paragraph = cells[cell_index].paragraphs[0]
            _add_inline_runs(paragraph, row[cell_index] if cell_index < len(row) else "")

    return index


def build_docx(plan: InterviewPlan) -> bytes:
    """把面试方案转换为 Word 文档字节。"""
    from docx import Document

    document = Document()
    _configure_document(document)

    document.add_heading(f"{plan.candidate_name} 面试方案", level=1)
    meta = document.add_paragraph()
    meta.add_run("应聘岗位：").bold = True
    meta.add_run(plan.candidate_position)
    if plan.job_title:
        meta = document.add_paragraph()
        meta.add_run("关联 JD：").bold = True
        meta.add_run(plan.job_title)
    document.add_paragraph()

    lines = plan.content.splitlines()
    in_code_block = False
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if _FENCE.match(line):
            in_code_block = not in_code_block
            index += 1
            continue

        if in_code_block:
            paragraph = document.add_paragraph()
            run = paragraph.add_run(line)
            run.font.name = "Consolas"
            index += 1
            continue

        if _is_table_start(lines, index):
            index = _add_table(document, lines, index)
            continue

        heading = _HEADING.match(line)
        if heading:
            level = min(len(heading.group(1)), 4)
            document.add_heading(heading.group(2).strip(), level=level)
            index += 1
            continue

        if not line.strip() or _RULE.match(line):
            index += 1
            continue

        bullet = _BULLET.match(line)
        if bullet:
            _add_inline_runs(document.add_paragraph(style="List Bullet"), bullet.group(1))
            index += 1
            continue

        ordered = _ORDERED.match(line)
        if ordered:
            _add_inline_runs(document.add_paragraph(style="List Number"), ordered.group(1))
            index += 1
            continue

        quote = _QUOTE.match(line)
        if quote:
            paragraph = document.add_paragraph(style="Intense Quote")
            _add_inline_runs(paragraph, quote.group(1))
            index += 1
            continue

        _add_inline_runs(document.add_paragraph(), line)
        index += 1

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
