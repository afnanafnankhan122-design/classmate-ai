from io import BytesIO
import csv
from datetime import date
from dataclasses import dataclass
from html import unescape
from io import StringIO
import re
from xml.sax.saxutils import escape

from fastapi import HTTPException

from app.services.assignment_evidence import mark_unverified_screenshot_placeholders
from app.services.assignment_figures import (
    AssignmentFigure,
    AssignmentFigureGenerationError,
    prepare_assignment_figures,
)


def _title_page_details(assignment, user) -> list[tuple[str, str]]:
    course = getattr(assignment, "course", None)
    instructor = getattr(assignment, "teacher_name", None) or getattr(
        course, "teacher_name", None
    )
    details = [
        ("Student Name", user.full_name),
        ("Student ID", user.roll_number),
        ("Instructor", instructor),
        ("Department", user.department),
        ("Semester", user.semester),
        ("Course", course.course_name if course else None),
        ("Date", date.today().strftime("%B %d, %Y")),
    ]
    return [(label, value) for label, value in details if value and value.strip()]


def _clean_assignment_title(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None

    source = _normalize_export_text(value).strip()
    if source.count("*") % 2 or source.count("`") % 2:
        return None

    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for character in source:
        if character in "([{":
            stack.append(character)
        elif character in pairs:
            if not stack or stack.pop() != pairs[character]:
                return None
    if stack:
        return None

    display = "".join(fragment.text for fragment in _parse_inline(source)).strip()
    if not display or not re.search(r"[A-Za-z0-9]", display):
        return None
    return display


def _display_assignment_title(value: object) -> str:
    return _clean_assignment_title(value) or "Assignment Title"


def _normalize_assignment_title_metadata(content: str, title: object) -> str:
    display_title = _clean_assignment_title(title)
    lines = content.splitlines()
    title_line = re.compile(
        r"^(\s*(?:\*\*)?Assignment Title:(?:\*\*)?\s*)(.*)$",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        match = title_line.match(line)
        if match:
            content_title = _clean_assignment_title(match.group(2))
            effective_title = display_title or content_title
            if effective_title is None:
                lines.pop(index)
            else:
                lines[index] = f"{match.group(1)}{effective_title}"
            break
    return "\n".join(lines)


_TABLE_SEPARATOR = re.compile(r":?-{3,}:?")
_CHECKLIST_ITEM = re.compile(r"^\s*(?:[-*+]\s*)?(?:\[[ xX]\]|[☐☑☒□■])\s*")
_INLINE_MARKDOWN = re.compile(
    r"(?P<link>\[([^\]\n]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\))"
    r"|(?P<strong>\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__)"
    r"|(?P<em>(?<!\*)\*(?!\s)(.+?)(?<=\S)\*(?!\*)|(?<!\w)_(?![\s_])(.+?)(?<=\S)_(?!\w))"
    r"|(?P<code>`([^`\n]+)`)",
    re.DOTALL,
)


@dataclass(frozen=True)
class _InlineFragment:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    link: str | None = None


@dataclass(frozen=True)
class _NumberedItem:
    number: str
    text: str


def _table_is_compact(rows: list[list[str]]) -> bool:
    return (
        1 < len(rows) <= 10
        and sum(len(cell) for row in rows for cell in row) <= 2500
        and max((len(cell) for row in rows for cell in row), default=0) <= 500
    )


def _slugify_heading(text: str) -> str:
    plain_text = "".join(fragment.text for fragment in _parse_inline(text))
    plain_text = re.sub(r"^\s*\d+[.)]\s*", "", plain_text)
    return re.sub(r"-+", "-", re.sub(r"[^\w-]+", "-", plain_text.casefold())).strip("-")


def _heading_anchors(
    blocks: list[tuple[str, object]],
) -> dict[str, str]:
    anchors: dict[str, str] = {}
    for (kind, value), anchor in zip(
        blocks,
        _heading_anchor_sequence(blocks),
        strict=True,
    ):
        if not kind.startswith("heading") or not isinstance(value, str):
            continue
        slug = _slugify_heading(value)
        if not slug:
            continue
        anchors.setdefault(slug, anchor)
        without_number = re.sub(r"^\s*\d+[.)]\s*", "", value)
        alias = _slugify_heading(without_number)
        if alias:
            anchors.setdefault(alias, anchor)
    return anchors


def _heading_anchor_sequence(blocks: list[tuple[str, object]]) -> list[str]:
    counts: dict[str, int] = {}
    sequence: list[str] = []
    for kind, value in blocks:
        if not kind.startswith("heading") or not isinstance(value, str):
            sequence.append("")
            continue
        slug = _slugify_heading(value)
        if not slug:
            sequence.append("")
            continue
        counts[slug] = counts.get(slug, 0) + 1
        sequence.append(slug if counts[slug] == 1 else f"{slug}-{counts[slug]}")
    return sequence


def _parse_inline(
    text: str,
    anchors: dict[str, str] | None = None,
    *,
    bold: bool = False,
    italic: bool = False,
    code: bool = False,
    link: str | None = None,
) -> list[_InlineFragment]:
    fragments: list[_InlineFragment] = []
    cursor = 0
    for match in _INLINE_MARKDOWN.finditer(text):
        if match.start() > cursor:
            fragments.append(_InlineFragment(text[cursor : match.start()], bold, italic, code, link))
        if match.group("link"):
            label, destination = match.group(2), match.group(3)
            resolved_link = None
            if destination.startswith("#"):
                anchor = (anchors or {}).get(_slugify_heading(destination[1:]))
                resolved_link = f"#{anchor}" if anchor else None
            elif destination.startswith(("https://", "http://", "mailto:")):
                resolved_link = destination
            fragments.extend(
                _parse_inline(
                    label,
                    anchors,
                    bold=bold,
                    italic=italic,
                    code=code,
                    link=resolved_link,
                )
            )
        elif match.group("strong"):
            inner = match.group(5) or match.group(6)
            fragments.extend(
                _parse_inline(inner, anchors, bold=True, italic=italic, code=code, link=link)
            )
        elif match.group("em"):
            inner = match.group(8) or match.group(9)
            fragments.extend(
                _parse_inline(inner, anchors, bold=bold, italic=True, code=code, link=link)
            )
        else:
            fragments.append(
                _InlineFragment(match.group(11), bold, italic, True, link)
            )
        cursor = match.end()
    if cursor < len(text):
        fragments.append(_InlineFragment(text[cursor:], bold, italic, code, link))
    return fragments


def _pdf_inline_markup(text: str, anchors: dict[str, str] | None = None) -> str:
    output: list[str] = []
    for fragment in _parse_inline(text, anchors):
        value = escape(fragment.text).replace("\n", "<br/>")
        if fragment.code:
            value = f'<font name="Courier">{value}</font>'
        if fragment.italic:
            value = f"<i>{value}</i>"
        if fragment.bold:
            value = f"<b>{value}</b>"
        if fragment.link:
            value = f'<link href="{escape(fragment.link, {chr(34): "&quot;"})}">{value}</link>'
        output.append(value)
    return "".join(output)


def _docx_add_inline(
    paragraph,
    text: str,
    anchors: dict[str, str] | None = None,
    *,
    hyperlink_factory=None,
) -> None:
    from docx.shared import RGBColor

    for fragment in _parse_inline(text, anchors):
        if fragment.link and hyperlink_factory:
            run = hyperlink_factory(paragraph, fragment.link)
        else:
            run = paragraph.add_run()
        run.text = fragment.text
        run.bold = fragment.bold or None
        run.italic = fragment.italic or None
        if fragment.code:
            run.font.name = "Courier New"
        if fragment.link:
            run.font.color.rgb = RGBColor(0x05, 0x63, 0xC1)
            run.underline = True


def _normalize_export_text(content: str) -> str:
    decoded = content
    for _ in range(3):
        unescaped = unescape(decoded)
        if unescaped == decoded:
            break
        decoded = unescaped
    decoded = decoded.translate(
        str.maketrans(
            {
                "\u2010": "-",
                "\u2011": "-",
                "\u2012": "-",
                "\u2013": "-",
                "\u2014": "-",
                "\u2212": "-",
                "\u2018": "'",
                "\u2019": "'",
                "\u201c": '"',
                "\u201d": '"',
                "\u2192": " -> ",
                "\u2190": " <- ",
                "\u2194": " <-> ",
                "\u2026": "...",
            }
        )
    )

    normalized_lines: list[str] = []
    in_code = False
    for line in decoded.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            normalized_lines.append(line)
            continue
        if not in_code:
            line = _normalize_escaped_markdown(line)
        line = re.sub(
            r"(?i)\b(Figures?\s+\d+)\s*[■□]\s*(\d+)\b",
            r"\1-\2",
            line,
        )
        if _CHECKLIST_ITEM.match(line):
            line = re.sub(r"^(\s*(?:[-*+]\s*)?)[☐□■]", r"\1[ ]", line)
            line = re.sub(r"^(\s*(?:[-*+]\s*)?)[☑☒]", r"\1[x]", line)
        else:
            line = line.replace("☐", "[ ]").replace("□", "[ ]")
            line = line.replace("☑", "[x]").replace("☒", "[x]")
        normalized_lines.append(line)
    return "\n".join(normalized_lines)


def _normalize_escaped_markdown(line: str) -> str:
    pieces = re.split(r"(`[^`]*`)", line)
    for index in range(0, len(pieces), 2):
        piece = pieces[index]
        piece = re.sub(r"^(\s*)\\(#{1,6})(?=\s)", r"\1\2", piece)
        piece = re.sub(r"\\\*\\\*(.+?)\\\*\\\*", r"**\1**", piece)
        piece = re.sub(r"\\__(.+?)\\__", r"__\1__", piece)
        piece = re.sub(
            r"(?<!\\)\\\*(?!\s)(.+?)(?<=\S)\\\*(?!\*)",
            r"*\1*",
            piece,
        )
        piece = re.sub(
            r"(?<!\\)\\_(?![\s_])(.+?)(?<=\S)\\_(?!\w)",
            r"_\1_",
            piece,
        )
        pieces[index] = piece
    return "".join(pieces)


def _table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith(r"\|") and stripped.endswith(r"\|"):
        escaped_cells = re.split(r"(?<!\\)\\\|", stripped[2:-2])
        return [
            cell.strip().replace(r"\|", "|")
            for cell in escaped_cells
        ]
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]

    cells: list[str] = []
    cell: list[str] = []
    in_code = False
    escaped = False
    index = 0
    while index < len(stripped):
        char = stripped[index]
        if char == "\\" and not escaped:
            escaped = True
            index += 1
            continue
        if char == "`" and not escaped:
            in_code = not in_code
            cell.append(char)
        elif char == "|" and not escaped and not in_code:
            cells.append("".join(cell).strip().replace("\\|", "|"))
            cell.clear()
        else:
            if escaped:
                cell.append("\\")
            cell.append(char)
        escaped = False
        index += 1
    cells.append("".join(cell).strip().replace("\\|", "|"))
    return cells


def _is_table_row(line: str) -> bool:
    return "|" in line


def _is_table_separator(line: str, column_count: int) -> bool:
    if not _is_table_row(line):
        return False
    cells = _table_cells(line)
    return len(cells) == column_count and all(
        _TABLE_SEPARATOR.fullmatch(cell.replace(" ", "")) for cell in cells
    )


def _render_cell_text(value: str) -> str:
    return re.sub(r"(?i)<br\s*/?>", "\n", value).strip()


def _plain_lines(content: str) -> list[tuple[str, object]]:
    content = _normalize_export_text(content)
    blocks: list[tuple[str, object]] = []
    paragraph: list[str] = []
    code: list[str] = []
    table: list[list[str]] = []
    in_code = False

    def flush() -> None:
        if paragraph:
            blocks.append(("paragraph", " ".join(line.strip() for line in paragraph)))
            paragraph.clear()

    def flush_table() -> None:
        if table:
            blocks.append(("table", table.copy()))
            table.clear()

    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            flush_table()
            if in_code:
                blocks.append(("code", "\n".join(code)))
                code.clear()
            in_code = not in_code
            index += 1
        elif in_code:
            code.append(line.rstrip())
            index += 1
        elif match := re.fullmatch(r"\[\[GENERATED_FIGURE:(\d+)\]\]", stripped):
            flush()
            flush_table()
            blocks.append(("generated_figure", int(match.group(1))))
            index += 1
        elif re.fullmatch(r"(?:-{3,}|_{3,}|\*{3,})", stripped):
            flush()
            flush_table()
            blocks.append(("horizontal_rule", ""))
            index += 1
        elif (
            index + 1 < len(lines)
            and _is_table_row(line)
            and _is_table_separator(lines[index + 1], len(_table_cells(line)))
        ):
            flush()
            flush_table()
            header = [_render_cell_text(cell) for cell in _table_cells(line)]
            column_count = len(header)
            table.append(header)
            index += 2
            while index < len(lines) and _is_table_row(lines[index]):
                if _is_table_separator(lines[index], column_count):
                    index += 1
                    continue
                row = _table_cells(lines[index])
                if len(row) > column_count:
                    row = row[: column_count - 1] + [
                        " | ".join(row[column_count - 1 :])
                    ]
                elif len(row) < column_count:
                    row.extend([""] * (column_count - len(row)))
                table.append([_render_cell_text(cell) for cell in row])
                index += 1
            while (
                index < len(lines)
                and lines[index].strip()
                and _CHECKLIST_ITEM.match(lines[index])
                and table
            ):
                checklist = lines[index].strip()
                table[-1][-1] = "\n".join(
                    part for part in (table[-1][-1], checklist) if part
                )
                index += 1
            flush_table()
        elif not stripped:
            flush()
            flush_table()
            index += 1
        elif match := re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", stripped):
            flush()
            flush_table()
            heading_level, heading = len(match.group(1)), match.group(2).strip()
            if heading:
                blocks.append((f"heading{heading_level}", heading))
            index += 1
        elif re.match(r"^[-*+•]\s+", stripped):
            flush()
            flush_table()
            blocks.append(("bullet", re.sub(r"^[-*+•]\s+", "", stripped)))
            index += 1
        elif match := re.match(r"^(\d+)[.)]\s+(.+)$", stripped):
            flush()
            flush_table()
            blocks.append(("numbered", _NumberedItem(match.group(1), match.group(2))))
            index += 1
        elif re.match(
            r"^\*\*(?:Assignment Title|Course|Student Name|Student ID|Instructor|Date):\*\*",
            stripped,
            re.IGNORECASE,
        ):
            flush()
            flush_table()
            blocks.append(("paragraph", stripped))
            index += 1
        elif stripped.startswith("Student Action Required —"):
            flush()
            flush_table()
            blocks.append(("screenshot_placeholder", stripped))
            index += 1
        else:
            flush_table()
            paragraph.append(stripped)
            index += 1
    if in_code:
        blocks.append(("code", "\n".join(code)))
    flush()
    merged_blocks: list[tuple[str, object]] = []
    for kind, value in blocks:
        previous_value = merged_blocks[-1][1] if merged_blocks else None
        if (
            kind == "table"
            and merged_blocks
            and merged_blocks[-1][0] == "table"
            and isinstance(previous_value, list)
            and isinstance(value, list)
            and _same_table_header(previous_value, value)
        ):
            merged_rows = previous_value + value[1:]
            merged_blocks[-1] = ("table", merged_rows)
        else:
            merged_blocks.append((kind, value))
    return merged_blocks


def _same_table_header(
    left: list[list[str]],
    right: list[list[str]],
) -> bool:
    if not left or not right:
        return False
    return [cell.strip().casefold() for cell in left[0]] == [
        cell.strip().casefold() for cell in right[0]
    ]


def _prepare_export_content(
    assignment,
    content: str,
) -> tuple[str, dict[int, AssignmentFigure]]:
    try:
        return prepare_assignment_figures(
            content,
            getattr(assignment, "description", None),
            getattr(assignment, "title", None),
        )
    except AssignmentFigureGenerationError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Mandatory assignment figures could not be generated: {exc}",
        ) from exc


def make_schedule_csv(content: str) -> bytes:
    required_headers = (
        "id",
        "task name",
        "duration",
        "start",
        "finish",
        "predecessors",
        "milestone",
    )
    schedule_rows: list[list[str]] | None = None
    for kind, value in _plain_lines(content):
        if kind != "table":
            continue
        rows = value
        if not rows:
            continue
        headers = [re.sub(r"\s+", " ", cell).strip().casefold() for cell in rows[0]]
        if all(header in headers for header in required_headers):
            column_indices = [headers.index(header) for header in required_headers]
            schedule_rows = [
                [row[index].strip() for index in column_indices]
                for row in rows[1:]
                if any(cell.strip() for cell in row)
            ]
            break

    rows = schedule_rows or []
    task_ids = [row[0] for row in rows]
    valid_ids = set(task_ids)
    if len(task_ids) != len(valid_ids) or any(not task_id.isdigit() for task_id in task_ids):
        raise HTTPException(
            status_code=409,
            detail="The project schedule must use unique numeric task IDs.",
        )

    for row in rows:
        task_id, task_name, duration, start, finish, predecessors, milestone = row
        is_milestone = milestone.casefold() in {"yes", "true"}
        try:
            start_date = date.fromisoformat(start)
            finish_date = date.fromisoformat(finish)
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail="The project schedule must use YYYY-MM-DD start and finish dates.",
            ) from exc
        duration_match = re.fullmatch(r"(\d+)d", duration.casefold())
        if (
            not task_name
            or duration_match is None
            or finish_date < start_date
            or (is_milestone and duration_match.group(1) != "0")
            or (not is_milestone and duration_match.group(1) == "0")
        ):
            raise HTTPException(
                status_code=409,
                detail="Each project schedule row needs a task, valid duration, dates, and milestone flag.",
            )
        predecessor_ids = [
            item.strip()
            for item in re.split(r"[,;]", predecessors)
            if item.strip() and item.strip().casefold() != "none"
        ]
        if any(
            predecessor_id not in valid_ids
            or int(predecessor_id) >= int(task_id)
            for predecessor_id in predecessor_ids
        ):
            raise HTTPException(
                status_code=409,
                detail="Project schedule predecessors must refer to earlier task IDs.",
            )

    non_milestone_tasks = [
        row for row in schedule_rows or [] if row[6].casefold() not in {"yes", "true"}
    ]
    milestone_tasks = [
        row for row in schedule_rows or [] if row[6].casefold() in {"yes", "true"}
    ]
    if len(non_milestone_tasks) < 8 or not milestone_tasks:
        raise HTTPException(
            status_code=409,
            detail=(
                "A Microsoft Project CSV is available only when the saved draft "
                "contains at least 8 scheduled tasks and a milestone in the required format."
            ),
        )

    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        ["ID", "Task Name", "Duration", "Start", "Finish", "Predecessors", "Milestone"]
    )
    writer.writerows(schedule_rows)
    return output.getvalue().encode("utf-8-sig")


def make_pdf(assignment, user, content: str) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
        from reportlab.platypus import HRFlowable
        from reportlab.platypus import Table, TableStyle
        from reportlab.platypus import (
            Image as PDFImage,
            KeepTogether,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="PDF export requires the installed ReportLab dependency.",
        ) from exc

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            page_count = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.setFont("Helvetica", 9)
                self.setFillColor(colors.HexColor("#5B6472"))
                self.drawCentredString(
                    letter[0] / 2,
                    0.45 * inch,
                    f"{self._pageNumber} / {page_count}",
                )
                canvas.Canvas.showPage(self)
            canvas.Canvas.save(self)

    class AssignmentDocTemplate(SimpleDocTemplate):
        def afterFlowable(self, flowable):
            anchor = getattr(flowable, "_assignment_anchor", None)
            if anchor:
                self.canv.bookmarkPage(anchor)

    buffer = BytesIO()
    document = AssignmentDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.85 * inch,
        leftMargin=0.85 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        title=_display_assignment_title(getattr(assignment, "title", None)),
        author=user.full_name,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AssignmentTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=28,
        textColor=colors.HexColor("#172554"),
        spaceAfter=24,
    )
    detail_style = ParagraphStyle(
        "AssignmentDetail",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=12,
        leading=20,
        textColor=colors.HexColor("#334155"),
    )
    cover_label_style = ParagraphStyle(
        "AssignmentCoverLabel",
        parent=detail_style,
        alignment=TA_LEFT,
        fontName="Helvetica-Bold",
        fontSize=10,
    )
    cover_value_style = ParagraphStyle(
        "AssignmentCoverValue",
        parent=detail_style,
        alignment=TA_LEFT,
        fontSize=10,
    )
    body_style = ParagraphStyle(
        "AssignmentBody",
        parent=styles["BodyText"],
        alignment=TA_LEFT,
        fontName="Times-Roman",
        fontSize=11,
        leading=17,
        spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "AssignmentHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#172554"),
        spaceBefore=12,
        spaceAfter=7,
    )
    code_style = ParagraphStyle(
        "AssignmentCode",
        parent=body_style,
        fontName="Courier",
        fontSize=8,
        leading=11,
        leftIndent=8,
        rightIndent=8,
        backColor=colors.HexColor("#F1F5F9"),
        borderColor=colors.HexColor("#CBD5E1"),
        borderWidth=0.5,
        borderPadding=6,
        spaceBefore=4,
        spaceAfter=10,
    )
    table_cell_style = ParagraphStyle(
        "AssignmentTableCell",
        parent=body_style,
        fontSize=9,
        leading=12,
        spaceAfter=0,
    )
    screenshot_placeholder_style = ParagraphStyle(
        "ScreenshotActionRequired",
        parent=body_style,
        backColor=colors.HexColor("#FFF7ED"),
        borderColor=colors.HexColor("#FB923C"),
        borderWidth=0.75,
        borderPadding=7,
        spaceBefore=5,
    )
    story = [
        Spacer(1, 1.15 * inch),
        Paragraph(
            _pdf_inline_markup(_display_assignment_title(getattr(assignment, "title", None))),
            title_style,
        ),
        HRFlowable(
            width="45%",
            thickness=1.5,
            color=colors.HexColor("#2563EB"),
            hAlign="CENTER",
            spaceAfter=20,
        ),
    ]
    cover_rows = [
        [
            Paragraph(escape(label), cover_label_style),
            Paragraph(escape(value), cover_value_style),
        ]
        for label, value in _title_page_details(assignment, user)
    ]
    if cover_rows:
        cover_table = Table(cover_rows, colWidths=[1.35 * inch, 4.65 * inch], hAlign="CENTER")
        cover_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EFF6FF")),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E2E8F0")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(cover_table)
    story.append(PageBreak())
    content = _normalize_assignment_title_metadata(
        content,
        getattr(assignment, "title", None),
    )
    content = mark_unverified_screenshot_placeholders(
        content,
        getattr(assignment, "description", None),
    )
    content, figures = _prepare_export_content(assignment, content)
    blocks = _plain_lines(content)
    anchors = _heading_anchors(blocks)
    heading_sequence = _heading_anchor_sequence(blocks)
    figure_caption_style = ParagraphStyle(
        "GeneratedFigureCaption",
        parent=body_style,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#334155"),
        spaceAfter=12,
    )
    for block_index, (kind, value) in enumerate(blocks):
        if kind == "generated_figure":
            figure = figures.get(value)
            if figure is None:
                raise HTTPException(
                    status_code=503,
                    detail="A required assignment figure was not available for PDF export.",
                )
            rendered_image = PDFImage(
                BytesIO(figure.image),
                width=6.7 * inch,
                height=5.0 * inch,
                kind="proportional",
                hAlign="CENTER",
            )
            story.append(
                KeepTogether(
                    [
                        rendered_image,
                        Spacer(1, 4),
                        Paragraph(
                            escape(f"Figure {figure.number}: {figure.caption}"),
                            figure_caption_style,
                        ),
                    ]
                )
            )
            continue
        if kind == "table":
            rows = value
            table_data = [
                [
                    Paragraph(_pdf_inline_markup(cell, anchors), table_cell_style)
                    for cell in row
                ]
                for row in rows
            ]
            rendered_table = Table(table_data, repeatRows=1, hAlign="LEFT")
            rendered_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            if _table_is_compact(rows):
                story.append(KeepTogether([rendered_table, Spacer(1, 8)]))
            else:
                story.append(rendered_table)
                story.append(Spacer(1, 8))
            continue
        text = value
        if kind == "bullet":
            story.append(Paragraph(_pdf_inline_markup(text, anchors), body_style, bulletText="-"))
        elif kind == "numbered":
            item = text
            story.append(
                Paragraph(
                    _pdf_inline_markup(item.text, anchors),
                    body_style,
                    bulletText=f"{item.number}.",
                )
            )
        elif kind == "horizontal_rule":
            story.append(
                HRFlowable(
                    width="100%",
                    thickness=0.7,
                    color=colors.HexColor("#94A3B8"),
                    spaceBefore=5,
                    spaceAfter=9,
                )
            )
        else:
            style = {
                "heading1": styles["Heading1"],
                "heading2": heading_style,
                "heading3": styles["Heading3"],
                "heading4": styles["Heading4"],
                "heading5": styles["Heading5"],
                "heading6": styles["Heading6"],
                "code": code_style,
                "screenshot_placeholder": screenshot_placeholder_style,
            }.get(kind, body_style)
            paragraph_markup = (
                escape(text).replace("\n", "<br/>")
                if kind == "code"
                else _pdf_inline_markup(text, anchors)
            )
            paragraph = Paragraph(paragraph_markup, style)
            if kind.startswith("heading"):
                paragraph.keepWithNext = 1
                anchor = heading_sequence[block_index]
                if anchor:
                    paragraph._assignment_anchor = anchor
            story.append(paragraph)
    document.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()


def make_docx(assignment, user, content: str) -> bytes:
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.opc.constants import RELATIONSHIP_TYPE
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Inches, Pt, RGBColor
        from docx.text.run import Run
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="DOCX export requires the installed python-docx dependency.",
        ) from exc

    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.8)
    section.bottom_margin = Inches(0.8)
    section.left_margin = Inches(0.9)
    section.right_margin = Inches(0.9)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(100)
    title.paragraph_format.space_after = Pt(24)
    _docx_add_inline(
        title,
        _display_assignment_title(getattr(assignment, "title", None)),
    )
    for run in title.runs:
        run.bold = True
        run.font.size = Pt(22)
        run.font.color.rgb = RGBColor(0x17, 0x25, 0x54)
    title_rule = document.add_paragraph()
    title_rule.paragraph_format.space_after = Pt(18)
    p_borders = OxmlElement("w:pBdr")
    bottom_border = OxmlElement("w:bottom")
    bottom_border.set(qn("w:val"), "single")
    bottom_border.set(qn("w:sz"), "12")
    bottom_border.set(qn("w:space"), "1")
    bottom_border.set(qn("w:color"), "2563EB")
    p_borders.append(bottom_border)
    title_rule._p.get_or_add_pPr().append(p_borders)
    for label, value in _title_page_details(assignment, user):
        detail = document.add_paragraph()
        detail.alignment = WD_ALIGN_PARAGRAPH.CENTER
        detail.paragraph_format.space_after = Pt(5)
        detail.add_run(f"{label}: ").bold = True
        detail.add_run(value)
    document.add_page_break()

    content = _normalize_assignment_title_metadata(
        content,
        getattr(assignment, "title", None),
    )
    content = mark_unverified_screenshot_placeholders(
        content,
        getattr(assignment, "description", None),
    )
    content, figures = _prepare_export_content(assignment, content)
    blocks = _plain_lines(content)
    anchors = _heading_anchors(blocks)
    heading_sequence = _heading_anchor_sequence(blocks)
    bookmark_id = 0

    def add_hyperlink(paragraph, target: str):
        hyperlink = OxmlElement("w:hyperlink")
        if target.startswith(("https://", "http://", "mailto:")):
            relationship_id = paragraph.part.relate_to(
                target,
                RELATIONSHIP_TYPE.HYPERLINK,
                is_external=True,
            )
            hyperlink.set(qn("r:id"), relationship_id)
        else:
            hyperlink.set(qn("w:anchor"), target.removeprefix("#"))
        run_element = OxmlElement("w:r")
        hyperlink.append(run_element)
        paragraph._p.append(hyperlink)
        return Run(run_element, paragraph)

    for block_index, (kind, value) in enumerate(blocks):
        if kind == "generated_figure":
            figure = figures.get(value)
            if figure is None:
                raise HTTPException(
                    status_code=503,
                    detail="A required assignment figure was not available for DOCX export.",
                )
            image_paragraph = document.add_paragraph()
            image_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            image_paragraph.paragraph_format.keep_with_next = True
            image_paragraph.add_run().add_picture(
                BytesIO(figure.image),
                width=Inches(6.2),
            )
            caption = document.add_paragraph()
            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
            caption.paragraph_format.keep_together = True
            caption.paragraph_format.keep_with_next = False
            caption_run = caption.add_run(
                f"Figure {figure.number}: {figure.caption}"
            )
            caption_run.bold = True
            caption_run.italic = True
            caption_run.font.size = Pt(9)
            continue
        if kind == "table":
            rows = value
            word_table = document.add_table(rows=0, cols=max(len(row) for row in rows))
            word_table.style = "Table Grid"
            for row_index, cells in enumerate(rows):
                word_row = word_table.add_row()
                row_properties = word_row._tr.get_or_add_trPr()
                cant_split = OxmlElement("w:cantSplit")
                row_properties.append(cant_split)
                if row_index == 0:
                    repeat_header = OxmlElement("w:tblHeader")
                    repeat_header.set(qn("w:val"), "true")
                    row_properties.append(repeat_header)
                row_cells = word_row.cells
                for column_index, text in enumerate(cells):
                    cell_paragraph = row_cells[column_index].paragraphs[0]
                    _docx_add_inline(
                        cell_paragraph,
                        text,
                        anchors,
                        hyperlink_factory=add_hyperlink,
                    )
                    if row_index == 0:
                        for run in cell_paragraph.runs:
                            run.bold = True
                    if _table_is_compact(rows) and row_index < len(rows) - 1:
                        cell_paragraph.paragraph_format.keep_with_next = True
            continue
        text = value
        if kind == "bullet":
            paragraph = document.add_paragraph(style="List Bullet")
            _docx_add_inline(paragraph, text, anchors, hyperlink_factory=add_hyperlink)
        elif kind == "numbered":
            item = text
            paragraph = document.add_paragraph(style="Normal")
            paragraph.paragraph_format.left_indent = Inches(0.25)
            paragraph.paragraph_format.first_line_indent = Inches(-0.25)
            paragraph.add_run(f"{item.number}. ")
            _docx_add_inline(
                paragraph,
                item.text,
                anchors,
                hyperlink_factory=add_hyperlink,
            )
        elif kind == "code":
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Inches(0.15)
            run = paragraph.add_run(text)
            run.font.name = "Courier New"
            run.font.size = Pt(9)
        elif kind == "horizontal_rule":
            paragraph = document.add_paragraph()
            borders = OxmlElement("w:pBdr")
            bottom = OxmlElement("w:bottom")
            bottom.set(qn("w:val"), "single")
            bottom.set(qn("w:sz"), "6")
            bottom.set(qn("w:space"), "1")
            bottom.set(qn("w:color"), "94A3B8")
            borders.append(bottom)
            paragraph._p.get_or_add_pPr().append(borders)
        elif kind == "screenshot_placeholder":
            paragraph = document.add_paragraph()
            _docx_add_inline(paragraph, text, anchors, hyperlink_factory=add_hyperlink)
            for run in paragraph.runs:
                run.bold = True
                run.font.color.rgb = RGBColor(0x9A, 0x34, 0x12)
            shading = OxmlElement("w:shd")
            shading.set(qn("w:fill"), "FFF7ED")
            paragraph._p.get_or_add_pPr().append(shading)
        else:
            heading_level = (
                int(kind.removeprefix("heading"))
                if kind.startswith("heading")
                else None
            )
            paragraph = document.add_paragraph(
                style=f"Heading {heading_level}" if heading_level else "Normal"
            )
            if heading_level:
                paragraph.paragraph_format.keep_with_next = True
            _docx_add_inline(
                paragraph,
                text,
                anchors,
                hyperlink_factory=add_hyperlink,
            )
            if heading_level:
                anchor = heading_sequence[block_index]
                if anchor:
                    bookmark_start = OxmlElement("w:bookmarkStart")
                    bookmark_start.set(qn("w:id"), str(bookmark_id))
                    bookmark_start.set(qn("w:name"), anchor)
                    bookmark_end = OxmlElement("w:bookmarkEnd")
                    bookmark_end.set(qn("w:id"), str(bookmark_id))
                    paragraph._p.insert(0, bookmark_start)
                    paragraph._p.append(bookmark_end)
                    bookmark_id += 1

    normal_style = document.styles["Normal"]
    normal_style.font.name = "Times New Roman"
    normal_style.font.size = Pt(11)
    normal_style.paragraph_format.space_after = Pt(8)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run()
    for field_type, instruction in (("begin", None), ("instrText", " PAGE "), ("end", None)):
        field = OxmlElement("w:fldChar" if field_type != "instrText" else "w:instrText")
        if field_type == "instrText":
            field.set(qn("xml:space"), "preserve")
            field.text = instruction
        else:
            field.set(qn("w:fldCharType"), field_type)
        run._r.append(field)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def safe_filename(value: str) -> str:
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return filename[:80] or "assignment"
