from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from typing import Callable, Sequence
import unicodedata

from fastapi import HTTPException

from app.services.assignment_evidence import requires_genuine_screenshot


class AssignmentFigureGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssignmentFigure:
    number: int
    caption: str
    image: bytes


@dataclass(frozen=True)
class FigureDefinition:
    number: int
    caption: str
    renderer: Callable[..., bytes]
    arguments: tuple[object, ...] = ()


@dataclass(frozen=True)
class AssignmentFigurePack:
    matches: Callable[[str, str | None, str | None], bool]
    build: Callable[[str, str | None], tuple[str, Sequence[FigureDefinition]]]


@dataclass(frozen=True)
class Entity:
    name: str
    primary_key: str
    attributes: tuple[str, ...]


@dataclass(frozen=True)
class Relationship:
    parent: str
    child: str
    cardinality: str
    parent_cardinality: str = "1"


_FIGURE_CAPTIONS = (
    "Student Management System - High-level conceptual illustration",
    "UML Use Case Diagram - Actors and Interactions",
    "Entity-Relationship Diagram - Seven Entities, Keys, and Cardinalities",
    "Three-Tier System Architecture - User Interface, Application Logic, and Database",
    "Illustrative Testing Interface Mockup - Test Case Entry (Not a Real Application Screenshot)",
)
_REQUIRED_ENTITIES = {
    "student",
    "course",
    "enrollment",
    "teacher",
    "teaching_assign",
    "grade",
    "attendance",
}
_IMAGE_WIDTH = 1800
_IMAGE_HEIGHT = 1125
_PALETTE = {
    "ink": "#172554",
    "muted": "#475569",
    "line": "#64748B",
    "blue": "#DBEAFE",
    "teal": "#CCFBF1",
    "violet": "#EDE9FE",
    "amber": "#FEF3C7",
    "paper": "#FFFFFF",
    "background": "#F8FAFC",
    "border": "#94A3B8",
}
_ASSIGNMENT_FIGURE_PACKS: list[AssignmentFigurePack] = []


def register_assignment_figure_pack(pack: AssignmentFigurePack) -> None:
    _ASSIGNMENT_FIGURE_PACKS.append(pack)


def _clean_cell(text: str) -> str:
    text = re.sub(r"\\(\*\*|__)", r"\1", text)
    return re.sub(r"\*\*|__|`", "", text).strip()


def _markdown_rows(content: str, required_header: str) -> list[list[str]]:
    lines = content.splitlines()
    for index, line in enumerate(lines[:-1]):
        if "|" not in line:
            continue
        header = [_clean_cell(cell) for cell in _split_cells(line)]
        if not any(required_header.casefold() in cell.casefold() for cell in header):
            continue
        if not all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in _split_cells(lines[index + 1])):
            continue
        rows = [header]
        for data_line in lines[index + 2 :]:
            if "|" not in data_line:
                break
            row = [_clean_cell(cell) for cell in _split_cells(data_line)]
            if any(row):
                rows.append(row)
        return rows
    return []


def _split_cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith(r"\|") and stripped.endswith(r"\|"):
        return [
            cell.strip().replace(r"\|", "|")
            for cell in re.split(r"(?<!\\)\\\|", stripped[2:-2])
        ]
    line = stripped.strip("|")
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line)]


def _normalize_escaped_heading(line: str) -> str:
    return re.sub(r"^(\s*)\\(#{1,6})(?=\s)", r"\1\2", line)


def _parse_actors(content: str) -> list[tuple[str, list[str]]]:
    rows = _markdown_rows(content, "Actor")
    if not rows:
        raise AssignmentFigureGenerationError(
            "The required use-case actor table could not be read from the assignment draft."
        )
    actors = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        actor = _clean_cell(row[0])
        use_cases = [
            item.strip()
            for item in re.split(r",\s*(?![^()]*\))", row[1])
            if item.strip()
        ]
        if actor and use_cases:
            actors.append((actor, use_cases))
    if {name.casefold() for name, _ in actors} != {
        "administrator",
        "teacher",
        "student",
        "parent/guardian",
    }:
        raise AssignmentFigureGenerationError(
            "The assignment actor table must specify Administrator, Teacher, Student, and Parent/Guardian."
        )
    return actors


def _parse_entities(content: str) -> tuple[list[Entity], list[Relationship]]:
    rows = _markdown_rows(content, "Entity")
    if not rows or len(rows[0]) < 3:
        raise AssignmentFigureGenerationError(
            "The required database entity table could not be read from the assignment draft."
        )
    headers = [header.casefold() for header in rows[0]]
    entity_column = next(
        (i for i, header in enumerate(headers) if "entity" in header), None
    )
    pk_column = next(
        (i for i, header in enumerate(headers) if "primary key" in header), None
    )
    attributes_column = next(
        (i for i, header in enumerate(headers) if "attribute" in header), None
    )
    if entity_column is None or pk_column is None or attributes_column is None:
        raise AssignmentFigureGenerationError(
            "The database entity table must include entity, primary key, and attributes columns."
        )

    entities: list[Entity] = []
    for row in rows[1:]:
        if len(row) <= max(entity_column, pk_column, attributes_column):
            continue
        name = _clean_cell(row[entity_column])
        primary_key = _clean_cell(row[pk_column])
        attributes = tuple(
            _clean_cell(attribute)
            for attribute in re.split(r",\s*", row[attributes_column])
            if _clean_cell(attribute)
        )
        if name and primary_key:
            entities.append(Entity(name, primary_key, attributes))
    if {entity.name.casefold() for entity in entities} != _REQUIRED_ENTITIES:
        raise AssignmentFigureGenerationError(
            "The assignment ERD must specify Student, Course, Enrollment, Teacher, Teaching_Assign, Grade, and Attendance."
        )
    if any(not entity.attributes for entity in entities):
        raise AssignmentFigureGenerationError(
            "Every assignment ERD entity must specify its attributes."
        )

    relationships = _parse_relationships(content, entities)
    if len(relationships) != 6:
        raise AssignmentFigureGenerationError(
            "The assignment ERD must specify six valid relationships; "
            f"found {len(relationships)}. Check the relationship list for missing, "
            "malformed, ambiguous, or unsupported endpoint/cardinality formats."
        )
    return entities, relationships


_CARDINALITY_TOKEN = re.compile(
    r"(?i)(?<![\w])(?:0\s*\.\.\s*(?:1|\*)|1\s*\.\.\s*(?:\*|many|n)|"
    r"zero\s+or\s+one|one\s+or\s+many|one|many|[01*]|n)(?![\w])"
)


def _normalize_relationship_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return value.translate(
        str.maketrans(
            {
                "\u2010": "-",
                "\u2011": "-",
                "\u2012": "-",
                "\u2013": "-",
                "\u2014": "-",
                "\u2015": "-",
                "\u2212": "-",
                "\u2192": "->",
                "\u27f6": "->",
                "\u2794": "->",
                "\u201c": '"',
                "\u201d": '"',
                "\u2018": "'",
                "\u2019": "'",
            }
        )
    )


def _canonical_cardinality(value: str) -> str | None:
    normalized = re.sub(r"[\s()]", "", _normalize_relationship_text(value)).casefold()
    if normalized in {"1", "one"}:
        return "1"
    if normalized in {"*", "n", "many", "1..*", "1..many"}:
        return "*"
    if normalized in {"0..1", "zeroorone"}:
        return "0..1"
    if normalized in {"0..*", "0..many"}:
        return "0..*"
    return None


def _entity_occurrences(
    text: str,
    entities: Sequence[Entity],
) -> list[tuple[int, int, str]]:
    occurrences = []
    for entity in sorted(entities, key=lambda item: len(item.name), reverse=True):
        pattern = re.compile(
            rf"(?<![\w]){re.escape(entity.name)}(?![\w])",
            re.IGNORECASE,
        )
        occurrences.extend(
            (match.start(), match.end(), entity.name)
            for match in pattern.finditer(text)
        )
    selected: list[tuple[int, int, str]] = []
    for occurrence in sorted(occurrences, key=lambda item: (item[0], -(item[1] - item[0]))):
        if selected and occurrence[0] < selected[-1][1]:
            continue
        selected.append(occurrence)
    return selected


def _parse_relationship_line(
    source_line: str,
    entities: Sequence[Entity],
) -> Relationship | None:
    line = _normalize_relationship_text(source_line)
    line = re.sub(r"^\s*(?:[-+*]\s+|\d+[.)]\s+)", "", line)
    line = line.replace("**", "").replace("__", "").replace("`", "").strip()
    occurrences = _entity_occurrences(line, entities)
    if len(occurrences) < 2:
        return None

    left = occurrences[0]
    right = occurrences[1]
    between = line[left[1] : right[0]]
    after_right = line[right[1] :]
    cardinalities = [
        match.group(0) for match in _CARDINALITY_TOKEN.finditer(between)
    ]
    trailing_cardinalities = [
        match.group(0) for match in _CARDINALITY_TOKEN.finditer(after_right)
    ]

    if len(cardinalities) == 2:
        parent_value, child_value = cardinalities
    elif len(cardinalities) == 1 and len(trailing_cardinalities) == 1:
        parent_value, child_value = cardinalities[0], trailing_cardinalities[0]
    elif not cardinalities and len(trailing_cardinalities) == 2:
        parent_value, child_value = trailing_cardinalities
    else:
        return None

    parent_cardinality = _canonical_cardinality(parent_value)
    child_cardinality = _canonical_cardinality(child_value)
    if parent_cardinality is None or child_cardinality is None:
        return None
    return Relationship(
        parent=left[2],
        child=right[2],
        cardinality=child_cardinality,
        parent_cardinality=parent_cardinality,
    )


def _parse_relationships(content: str, entities: Sequence[Entity]) -> list[Relationship]:
    relationships: list[Relationship] = []
    seen: set[tuple[str, str]] = set()
    relationship_section = False
    errors: list[str] = []

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = _normalize_relationship_text(raw_line).strip()
        if not line:
            continue
        heading = re.match(r"^#{1,6}\s*(.+?)\s*#*$", line)
        if heading:
            heading_text = heading.group(1).strip("*_ ").casefold()
            relationship_section = bool(re.search(r"\brelationships?\b", heading_text))
            continue
        plain_heading = line.strip("*_ ").rstrip(": ").casefold()
        if re.fullmatch(
            r"(?:\d+[.)]\s*)?relationships?"
            r"(?:\s+to\s+\w+)?(?:\s*\([^)]*\))?",
            plain_heading,
        ):
            relationship_section = True
            continue
        if re.fullmatch(r"(?:-{3,}|_{3,}|\*{3,})", line):
            relationship_section = False
            continue
        if re.match(r"^\**explanation\s*:", line.replace("*", ""), re.IGNORECASE):
            relationship_section = False
            continue

        cells = _split_cells(line) if "|" in line else [line]
        if cells and all(
            re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells
        ):
            continue
        candidate_text = " ".join(cells)
        parsed = _parse_relationship_line(candidate_text, entities)
        if parsed is None:
            occurrences = _entity_occurrences(candidate_text, entities)
            cardinality_count = len(list(_CARDINALITY_TOKEN.finditer(candidate_text)))
            has_cardinality = cardinality_count > 0
            looks_like_relationship = cardinality_count >= 2 and bool(
                re.search(
                    r"(?:->|:|\bto\b|[-=]\s*(?:\*|many|n|1|0))",
                    candidate_text,
                    re.IGNORECASE,
                )
            )
            is_relationship_list_item = bool(
                re.match(r"^\s*(?:[-+*]\s+|\d+[.)]\s+)", line)
            )
            if relationship_section and looks_like_relationship and len(occurrences) < 2:
                errors.append(
                    f"line {line_number} could not resolve both endpoints to defined "
                    f"ERD entities: {raw_line.strip()!r}"
                )
            elif relationship_section and (
                looks_like_relationship
                or (is_relationship_list_item and len(occurrences) >= 2 and has_cardinality)
            ):
                errors.append(
                    f"line {line_number} uses an unsupported or ambiguous format: "
                    f"{raw_line.strip()!r}"
                )
            continue

        pair = (parsed.parent.casefold(), parsed.child.casefold())
        if pair in seen:
            errors.append(
                f"line {line_number} duplicates relationship "
                f"{parsed.parent} -> {parsed.child}"
            )
            continue
        seen.add(pair)
        relationships.append(parsed)

    if errors:
        raise AssignmentFigureGenerationError(
            "The assignment ERD contains invalid relationships: " + "; ".join(errors[:3])
        )
    if not relationships:
        raise AssignmentFigureGenerationError(
            "No ERD relationships were recognized. Use a list or table with two "
            "defined entity names and explicit cardinalities, such as "
            "'Student 1:* Enrollment' or 'Student (1) -> Enrollment (many)'."
        )
    unknown_relationships = [
        relationship
        for relationship in relationships
        if relationship.parent.casefold() not in {e.name.casefold() for e in entities}
        or relationship.child.casefold() not in {e.name.casefold() for e in entities}
    ]
    if unknown_relationships:
        raise AssignmentFigureGenerationError(
            "Every ERD relationship endpoint must match a defined entity."
        )
    return relationships


def _needs_student_management_figures(
    content: str,
    instructions: str | None,
    assignment_title: str | None,
) -> bool:
    combined = f"{assignment_title or ''}\n{instructions or ''}\n{content}".casefold()
    has_sms_context = "student management system" in combined
    has_mandatory_images = (
        "pictures and diagrams" in combined and "mandatory" in combined
    )
    has_complete_figure_specification = (
        "list of figures" in combined
        and "parent/guardian" in combined
        and "teaching_assign" in combined
    )
    return has_sms_context and (
        has_mandatory_images or has_complete_figure_specification
    )


def _canvas(width: int = _IMAGE_WIDTH, height: int = _IMAGE_HEIGHT):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Mandatory assignment figures require the installed Pillow dependency.",
        ) from exc

    image = Image.new("RGB", (width, height), _PALETTE["background"])
    draw = ImageDraw.Draw(image)
    font_root = "C:\\Windows\\Fonts"
    font_paths = {
        "regular": f"{font_root}\\arial.ttf",
        "bold": f"{font_root}\\arialbd.ttf",
        "italic": f"{font_root}\\ariali.ttf",
    }

    def font(size: int, weight: str = "regular"):
        try:
            return ImageFont.truetype(font_paths[weight], size)
        except OSError:
            return ImageFont.load_default()

    return Image, draw, image, font


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _draw_wrapped(draw, xy, text: str, font, fill: str, max_width: int, spacing: int = 8):
    x, y = xy
    lines = _wrap(draw, text, font, max_width)
    draw.multiline_text((x, y), "\n".join(lines), font=font, fill=fill, spacing=spacing)
    return len(lines) * (font.size + spacing)


def _png(Image, image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True, dpi=(220, 220))
    data = output.getvalue()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssignmentFigureGenerationError("A generated figure was not a valid PNG image.")
    return data


def _draw_header(draw, font, title: str, subtitle: str | None = None) -> None:
    draw.text((75, 35), title, font=font(42, "bold"), fill=_PALETTE["ink"])
    if subtitle:
        draw.text((78, 92), subtitle, font=font(24), fill=_PALETTE["muted"])


def _figure_1() -> bytes:
    Image, draw, image, font = _canvas()
    _draw_header(
        draw,
        font,
        "Student Management System",
        "Conceptual overview - illustrative design, not a screenshot of a running product",
    )
    draw.rounded_rectangle(
        (590, 330, 1210, 780),
        radius=34,
        fill=_PALETTE["paper"],
        outline=_PALETTE["ink"],
        width=5,
    )
    draw.rounded_rectangle(
        (625, 365, 1175, 445),
        radius=18,
        fill=_PALETTE["blue"],
        outline=_PALETTE["border"],
        width=2,
    )
    draw.text((685, 388), "Student records | Courses | Reports", font=font(25, "bold"), fill=_PALETTE["ink"])
    cards = [
        ("Enrollment", "Course registration and status", 650, 485, _PALETTE["teal"]),
        ("Grades", "Results and academic progress", 940, 485, _PALETTE["violet"]),
        ("Attendance", "Class attendance records", 650, 630, _PALETTE["amber"]),
        ("Communication", "Updates for families", 940, 630, _PALETTE["blue"]),
    ]
    for title, detail, x, y, color in cards:
        draw.rounded_rectangle((x, y, x + 250, y + 112), radius=16, fill=color, outline=_PALETTE["border"], width=2)
        draw.text((x + 16, y + 16), title, font=font(23, "bold"), fill=_PALETTE["ink"])
        _draw_wrapped(draw, (x + 16, y + 52), detail, font(17), _PALETTE["muted"], 215, 4)

    users = [
        ("Administrator", 220, _PALETTE["blue"]),
        ("Teacher", 425, _PALETTE["teal"]),
        ("Student", 690, _PALETTE["violet"]),
        ("Parent/Guardian", 895, _PALETTE["amber"]),
    ]
    for label, y, color in users:
        draw.rounded_rectangle((85, y, 405, y + 110), radius=22, fill=color, outline=_PALETTE["border"], width=3)
        draw.ellipse((112, y + 25, 162, y + 75), outline=_PALETTE["ink"], width=4)
        draw.arc((104, y + 55, 170, y + 108), 180, 360, fill=_PALETTE["ink"], width=4)
        draw.text((190, y + 36), label, font=font(24, "bold"), fill=_PALETTE["ink"])
        draw.line((405, y + 55, 575, y + 55), fill=_PALETTE["line"], width=4)
        draw.polygon([(575, y + 55), (558, y + 45), (558, y + 65)], fill=_PALETTE["line"])
    return _png(Image, image)


def _figure_2(actors: list[tuple[str, list[str]]]) -> bytes:
    Image, draw, image, font = _canvas()
    _draw_header(draw, font, "UML Use Case Diagram", "Actors and interactions from the assignment requirements")
    boundary = (340, 150, 1460, 1020)
    draw.rounded_rectangle(boundary, radius=18, fill="#FFFFFF", outline=_PALETTE["ink"], width=5)
    draw.text((705, 165), "Student Management System", font=font(30, "bold"), fill=_PALETTE["ink"])
    left_actors = actors[:2]
    right_actors = actors[2:]
    actor_positions = {
        left_actors[0][0]: (125, 365),
        left_actors[1][0]: (125, 800),
        right_actors[0][0]: (1670, 365),
        right_actors[1][0]: (1670, 800),
    }
    left_items = [(actor, case) for actor, cases in left_actors for case in cases]
    right_items: list[tuple[str | None, str]] = []
    for actor, cases in right_actors:
        for case in cases:
            right_items.append((actor, case))
            if case.casefold() == "register for courses":
                right_items.append((None, "Validate prerequisites"))
    left_items = left_items[:8]
    right_items = right_items[:8]
    slot_y = [255 + i * 90 for i in range(8)]

    def ellipse(x: int, y: int, label: str, actor: str | None, side: str):
        bounds = (x - 220, y - 34, x + 220, y + 34)
        draw.ellipse(bounds, fill="#F8FAFC", outline=_PALETTE["line"], width=3)
        _draw_wrapped(draw, (x - 195, y - 15), label, font(20), _PALETTE["ink"], 390, 2)
        if actor is not None:
            ax, ay = actor_positions[actor]
            start = (ax + 48 if side == "left" else ax - 48, ay - 10)
            end = (bounds[0] if side == "left" else bounds[2], y)
            draw.line((start, end), fill="#94A3B8", width=2)
        return bounds

    case_bounds = {}
    for i, (actor, case) in enumerate(left_items):
        case_bounds[case.casefold()] = ellipse(650, slot_y[i], case, actor, "left")
    for i, (actor, case) in enumerate(right_items):
        case_bounds[case.casefold()] = ellipse(1150, slot_y[i], case, actor, "right")

    for actor, (x, y) in actor_positions.items():
        draw.ellipse((x - 22, y - 150, x + 22, y - 106), outline=_PALETTE["ink"], width=4)
        draw.line((x, y - 106, x, y - 28), fill=_PALETTE["ink"], width=4)
        draw.line((x - 43, y - 80, x + 43, y - 80), fill=_PALETTE["ink"], width=4)
        draw.line((x, y - 28, x - 36, y + 25), fill=_PALETTE["ink"], width=4)
        draw.line((x, y - 28, x + 36, y + 25), fill=_PALETTE["ink"], width=4)
        label_lines = _wrap(draw, actor, font(21, "bold"), 240)
        draw.multiline_text((x - 120, y + 40), "\n".join(label_lines), font=font(21, "bold"), fill=_PALETTE["ink"], align="center")

    register_box = case_bounds.get("register for courses")
    validate_box = case_bounds.get("validate prerequisites")
    if register_box and validate_box:
        start = ((register_box[0] + register_box[2]) // 2, register_box[3])
        end = ((validate_box[0] + validate_box[2]) // 2, validate_box[1])
        dash_length = 9
        distance = end[1] - start[1]
        for offset in range(0, distance, dash_length * 2):
            draw.line(
                (start[0], start[1] + offset, end[0], min(start[1] + offset + dash_length, end[1] - 10)),
                fill=_PALETTE["muted"],
                width=2,
            )
        draw.polygon([end, (end[0] - 8, end[1] - 13), (end[0] + 8, end[1] - 13)], fill=_PALETTE["muted"])
        draw.text((1370, start[1] + 2), "<<include>>", font=font(14, "italic"), fill=_PALETTE["muted"])
    return _png(Image, image)


def _figure_3(entities: list[Entity], relationships: list[Relationship]) -> bytes:
    Image, draw, image, font = _canvas(1800, 1350)
    _draw_header(draw, font, "Entity-Relationship Diagram", "PK = primary key; FK = foreign key; crow's-foot end denotes many")
    positions = {
        "student": (65, 155),
        "course": (680, 155),
        "teacher": (1295, 155),
        "enrollment": (370, 590),
        "teaching_assign": (990, 590),
        "grade": (370, 1055),
        "attendance": (990, 1055),
    }
    width = 440
    row_height = 37
    header_height = 55
    bounds = {}
    for entity in entities:
        x, y = positions[entity.name.casefold()]
        height = header_height + (len(entity.attributes) + 1) * row_height
        bounds[entity.name.casefold()] = (x, y, x + width, y + height)

    def edge_point(box, other_center):
        x1, y1, x2, y2 = box
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        dx, dy = other_center[0] - cx, other_center[1] - cy
        if abs(dx) * (y2 - y1) > abs(dy) * (x2 - x1):
            return (x2 if dx > 0 else x1, int(cy))
        return (int(cx), y2 if dy > 0 else y1)

    for relationship in relationships:
        parent = relationship.parent.casefold()
        child = relationship.child.casefold()
        parent_box, child_box = bounds[parent], bounds[child]
        parent_center = ((parent_box[0] + parent_box[2]) // 2, (parent_box[1] + parent_box[3]) // 2)
        child_center = ((child_box[0] + child_box[2]) // 2, (child_box[1] + child_box[3]) // 2)
        start = edge_point(parent_box, child_center)
        end = edge_point(child_box, parent_center)
        draw.line((start, end), fill=_PALETTE["line"], width=4)
        draw.text(
            (start[0] + 8, start[1] + 7),
            relationship.parent_cardinality,
            font=font(21, "bold"),
            fill=_PALETTE["ink"],
        )
        many_label = relationship.cardinality
        dx, dy = end[0] - start[0], end[1] - start[1]
        draw.text((end[0] - (60 if dx > 0 else -12), end[1] - (25 if dy > 0 else -10)), many_label, font=font(21, "bold"), fill=_PALETTE["ink"])
        if "*" in relationship.parent_cardinality:
            draw.line((start, (start[0] - 14, start[1] - 12)), fill=_PALETTE["line"], width=3)
            draw.line((start, (start[0] - 14, start[1] + 12)), fill=_PALETTE["line"], width=3)
            draw.line((start, (start[0] + 1, start[1] + 15)), fill=_PALETTE["line"], width=3)
        if "*" in relationship.cardinality:
            draw.line((end, (end[0] - 14, end[1] - 12)), fill=_PALETTE["line"], width=3)
            draw.line((end, (end[0] - 14, end[1] + 12)), fill=_PALETTE["line"], width=3)
            draw.line((end, (end[0] + 1, end[1] + 15)), fill=_PALETTE["line"], width=3)

    for entity in entities:
        x, y = positions[entity.name.casefold()]
        box = bounds[entity.name.casefold()]
        draw.rounded_rectangle(box, radius=14, fill=_PALETTE["paper"], outline=_PALETTE["ink"], width=3)
        draw.rounded_rectangle((x, y, x + width, y + header_height), radius=14, fill=_PALETTE["blue"], outline=_PALETTE["ink"], width=2)
        draw.rectangle((x, y + header_height - 13, x + width, y + header_height), fill=_PALETTE["blue"])
        draw.text((x + 17, y + 11), entity.name, font=font(25, "bold"), fill=_PALETTE["ink"])
        fields = [(entity.primary_key, "PK"), *[(attribute, "FK" if "(FK)" in attribute.upper() else "") for attribute in entity.attributes]]
        for index, (field, key_type) in enumerate(fields):
            row_y = y + header_height + index * row_height
            if index:
                draw.line((x + 10, row_y, x + width - 10, row_y), fill="#E2E8F0", width=1)
            clean_field = re.sub(r"\s*\(FK\)\s*", "", field, flags=re.IGNORECASE)
            draw.text((x + 17, row_y + 7), clean_field, font=font(19), fill=_PALETTE["ink"])
            if key_type:
                draw.rounded_rectangle((x + width - 68, row_y + 5, x + width - 14, row_y + 32), radius=7, fill=_PALETTE["amber"])
                draw.text((x + width - 59, row_y + 7), key_type, font=font(15, "bold"), fill=_PALETTE["ink"])
    return _png(Image, image)


def _figure_4() -> bytes:
    Image, draw, image, font = _canvas()
    _draw_header(draw, font, "Three-Tier System Architecture", "Request and response flow between presentation, business logic, and data")
    boxes = [
        (100, 360, 585, 750, "User Interface", "Presentation Layer", "Web browser or\nmobile application", _PALETTE["blue"]),
        (655, 360, 1145, 750, "Application Logic", "Business Logic Layer", "REST API, controllers,\nvalidation and services", _PALETTE["teal"]),
        (1215, 360, 1700, 750, "Database", "Data Layer", "Relational database:\nstudents, courses, grades", _PALETTE["violet"]),
    ]
    for x1, y1, x2, y2, title, layer, detail, fill in boxes:
        draw.rounded_rectangle((x1, y1, x2, y2), radius=28, fill=fill, outline=_PALETTE["ink"], width=4)
        draw.text((x1 + 28, y1 + 60), title, font=font(30, "bold"), fill=_PALETTE["ink"])
        draw.text((x1 + 28, y1 + 115), layer, font=font(23, "bold"), fill=_PALETTE["muted"])
        draw.multiline_text((x1 + 28, y1 + 195), detail, font=font(23), fill=_PALETTE["ink"], spacing=12)

    def arrow(start, end, color, label, label_y):
        draw.line((start, end), fill=color, width=6)
        direction = 1 if end[0] > start[0] else -1
        draw.polygon(
            [
                end,
                (end[0] - 20 * direction, end[1] - 12),
                (end[0] - 20 * direction, end[1] + 12),
            ],
            fill=color,
        )
        center = (start[0] + end[0]) // 2
        draw.text((center - 65, label_y), label, font=font(19, "bold"), fill=color)

    for left, right in ((585, 655), (1145, 1215)):
        arrow((left, 490), (right, 490), "#2563EB", "Request", 455)
        arrow((right, 630), (left, 630), "#0F766E", "Response", 645)
    draw.text((575, 875), "Authentication and authorization are applied by the application logic.", font=font(22), fill=_PALETTE["muted"])
    return _png(Image, image)


def _figure_5() -> bytes:
    Image, draw, image, font = _canvas()
    _draw_header(
        draw,
        font,
        "Illustrative Testing Interface Mockup",
        "Example layout only - not a screenshot of a real application; no test has been executed",
    )
    x1, y1, x2, y2 = 145, 190, 1655, 1045
    draw.rounded_rectangle((x1, y1, x2, y2), radius=24, fill=_PALETTE["paper"], outline=_PALETTE["border"], width=3)
    draw.rounded_rectangle((x1, y1, x2, y1 + 72), radius=24, fill=_PALETTE["blue"], outline=_PALETTE["border"], width=2)
    draw.rectangle((x1, y1 + 48, x2, y1 + 72), fill=_PALETTE["blue"])
    draw.text((x1 + 28, y1 + 21), "Test Case Record", font=font(28, "bold"), fill=_PALETTE["ink"])
    fields = [
        ("Test ID", "TC-SMS-001"),
        ("Description", "Verify a student can register for an available course."),
        ("Preconditions", "Student account exists; course is open for enrollment."),
        ("Steps", "1. Sign in  2. Open Courses  3. Select Register"),
        ("Expected Result", "Enrollment is recorded and confirmation is shown."),
        ("Actual Result", "Not run - enter observed result after real execution."),
    ]
    y = y1 + 104
    for label, value in fields:
        draw.text((x1 + 30, y), label, font=font(20, "bold"), fill=_PALETTE["ink"])
        height = _draw_wrapped(draw, (x1 + 315, y), value, font(19), _PALETTE["muted"], 1215, 4)
        box_y = y + height + 10
        draw.line((x1 + 25, box_y, x2 - 25, box_y), fill="#E2E8F0", width=2)
        y = box_y + 18
    draw.text((x1 + 30, y + 3), "Pass/Fail", font=font(20, "bold"), fill=_PALETTE["ink"])
    draw.rounded_rectangle((x1 + 315, y, x1 + 440, y + 42), radius=8, outline=_PALETTE["border"], width=2)
    draw.text((x1 + 330, y + 8), "[ ] Pass", font=font(18), fill=_PALETTE["muted"])
    draw.rounded_rectangle((x1 + 465, y, x1 + 590, y + 42), radius=8, outline=_PALETTE["border"], width=2)
    draw.text((x1 + 480, y + 8), "[ ] Fail", font=font(18), fill=_PALETTE["muted"])
    draw.text((x1 + 710, y + 8), "Not run", font=font(18, "bold"), fill="#B45309")
    y += 62
    draw.text((x1 + 30, y + 3), "Comments", font=font(20, "bold"), fill=_PALETTE["ink"])
    draw.rounded_rectangle((x1 + 315, y, x2 - 30, min(y + 55, y2 - 20)), radius=8, outline=_PALETTE["border"], width=2)
    return _png(Image, image)


_RENDERERS: tuple[Callable[..., bytes], ...] = (
    _figure_1,
    _figure_2,
    _figure_3,
    _figure_4,
    _figure_5,
)


def render_figure_pack(
    definitions: Sequence[FigureDefinition],
) -> dict[int, AssignmentFigure]:
    if not definitions or [item.number for item in definitions] != list(
        range(1, len(definitions) + 1)
    ):
        raise AssignmentFigureGenerationError(
            "Assignment figures must be defined in sequential order starting at Figure 1."
        )

    figures: dict[int, AssignmentFigure] = {}
    for definition in definitions:
        if not definition.caption.strip():
            raise AssignmentFigureGenerationError(
                f"Figure {definition.number} needs a descriptive caption."
            )
        try:
            image = definition.renderer(*definition.arguments)
            if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                raise AssignmentFigureGenerationError(
                    f"Figure {definition.number} did not produce a valid PNG image."
                )
            from PIL import Image

            with Image.open(BytesIO(image)) as generated:
                generated.verify()
        except HTTPException:
            raise
        except AssignmentFigureGenerationError:
            raise
        except (ImportError, OSError, ValueError, TypeError) as exc:
            raise AssignmentFigureGenerationError(
                f"Figure {definition.number} could not be generated from the assignment requirements."
            ) from exc
        figures[definition.number] = AssignmentFigure(
            definition.number,
            definition.caption,
            image,
        )
    return figures


def _resolve_figure_markers(
    content: str,
    instructions: str | None = None,
) -> str:
    figure_sections = {
        1: re.compile(r"(?i)\b(?:high[- ]level (?:overview|conceptual illustration)|student management system.{0,40}(?:picture|illustration|overview))\b"),
        2: re.compile(r"(?i)\buse.case diagram\b"),
        3: re.compile(r"(?i)\b(?:entity.relationship diagram|\berd\b|database schema)\b"),
        4: re.compile(r"(?i)\b(?:system architecture|presentation, business logic)\b"),
        5: re.compile(r"(?i)\b(?:testing interface|sample testing interface|test case entry)\b"),
    }
    heading_sections = {
        1: re.compile(r"(?i)\bintroduction\b"),
        2: re.compile(r"(?i)\bsystem design\b"),
        3: re.compile(r"(?i)\bdatabase design\b"),
        4: re.compile(r"(?i)\bsystem architecture\b"),
        5: re.compile(r"(?i)\btesting\b"),
    }
    section_number = None
    inserted: set[int] = set()
    output: list[str] = []
    in_figures_list = False
    in_action_summary = False
    has_figures_list = False
    figure_list_heading: str | None = None
    action_summary_lines: list[str] = []
    preserved_screenshot_actions: set[int] = set()

    def flush_action_summary() -> None:
        retained = [
            line
            for line in action_summary_lines
            if not (
                (match := re.search(r"(?i)\b(?:Figure|Fig\.?)\s+(\d+)\b", line))
                and int(match.group(1)) <= 5
            )
        ]
        has_remaining_action = any(
            line.strip()
            and not re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", line)
            and (
                (
                    match := re.search(r"(?i)\b(?:Figure|Fig\.?)\s+(\d+)\b", line)
                )
                and int(match.group(1)) > 5
                or re.search(
                    r"(?i)\b(?:screenshot|screen capture|picture|image|illustration|diagram)\b",
                    line,
                )
                or (
                    not line.lstrip().startswith("|")
                    and not re.search(r"(?i)\bfigures?\b", line)
                )
            )
            for line in retained
        )
        if has_remaining_action:
            output.append("### Student Action Required Summary")
            output.extend(retained)
        action_summary_lines.clear()

    for line in content.splitlines():
        line = _normalize_escaped_heading(line)
        heading = re.match(r"^\s*#{1,6}\s*(.*?)\s*$", line)
        heading_text = _clean_cell(heading.group(1)) if heading else ""
        if heading_text.casefold().startswith("student action required summary"):
            in_action_summary = True
            action_summary_lines.clear()
            continue
        if in_action_summary:
            if not heading_text:
                match = re.search(r"(?i)\b(?:Figure|Fig\.?)\s+(\d+)\b", line)
                if match is None or int(match.group(1)) > 5:
                    action_summary_lines.append(line)
                continue
            flush_action_summary()
            in_action_summary = False
        if re.match(r"(?i)^(?:\d+\.\s*)?list of figures$", heading_text):
            in_figures_list = True
            has_figures_list = True
            figure_list_heading = line
            output.append("")
            continue
        if in_figures_list:
            if heading_text:
                in_figures_list = False
            else:
                continue
        if heading_text:
            title = re.sub(r"^\d+\.\s*", "", heading_text).casefold()
            section_number = next(
                (
                    number
                    for number, pattern in figure_sections.items()
                    if pattern.search(title)
                ),
                next(
                    (
                        number
                        for number, pattern in heading_sections.items()
                        if pattern.search(title)
                    ),
                    None,
                ),
            )
            output.append(line)
            continue

        figure_number = None
        for number, pattern in figure_sections.items():
            if pattern.search(line):
                figure_number = number
                break

        is_student_action = "student action required" in line.casefold()
        if is_student_action:
            explicit_number = re.search(
                r"(?i)\b(?:Figure|Fig\.?)\s+(\d+)\b",
                line,
            )
            if explicit_number and int(explicit_number.group(1)) > 5:
                output.append(line)
                continue
            if figure_number is None:
                if section_number is not None:
                    figure_number = section_number
                elif explicit_number is not None and int(explicit_number.group(1)) in figure_sections:
                    figure_number = int(explicit_number.group(1))
                elif not explicit_number and section_number is not None and re.search(
                    r"(?i)\b(?:screenshot|screen capture|picture|image|illustration|diagram)\b",
                    line,
                ):
                    figure_number = section_number
            if figure_number is not None and figure_number not in inserted:
                output.append(f"[[GENERATED_FIGURE:{figure_number}]]")
                if figure_number == 5:
                    output.append(
                        "This illustrative mockup displays Test ID, Description, "
                        "Preconditions, Steps, Expected Result, Actual Result, Pass/Fail, "
                        "and Comments. It is not a screenshot of a real application. "
                        "The actual result is unfilled and the status is Not run; "
                        "no real test execution is claimed."
                    )
                inserted.add(figure_number)
                if requires_genuine_screenshot(instructions, figure_number) and re.search(
                    r"(?i)\b(?:screenshot|screen capture)\b",
                    line,
                ):
                    output.append(
                        re.sub(
                            r"(?i)\b(Figure|Fig\.?)\s+\d+",
                            rf"\1 {figure_number}",
                            line,
                        )
                    )
                    preserved_screenshot_actions.add(figure_number)
                continue
            if figure_number in inserted:
                if (
                    requires_genuine_screenshot(instructions, figure_number)
                    and figure_number not in preserved_screenshot_actions
                    and re.search(r"(?i)\b(?:screenshot|screen capture)\b", line)
                ):
                    output.append(
                        re.sub(
                            r"(?i)\b(Figure|Fig\.?)\s+\d+",
                            rf"\1 {figure_number}",
                            line,
                        )
                    )
                    preserved_screenshot_actions.add(figure_number)
                continue
            output.append(line)
            continue

        if figure_number and figure_number not in inserted and (
            "figure" in line.casefold() or "screenshot" in line.casefold()
        ):
            output.append(f"[[GENERATED_FIGURE:{figure_number}]]")
            if figure_number == 5:
                output.append(
                    "This illustrative mockup displays Test ID, Description, "
                    "Preconditions, Steps, Expected Result, Actual Result, Pass/Fail, "
                    "and Comments. It is not a screenshot of a real application. "
                    "The actual result is unfilled and the status is Not run; "
                    "no real test execution is claimed."
                )
            inserted.add(figure_number)
            continue
        if re.search(r"(?i)\bBrief Explanation:", line):
            line = re.sub(r"(?i)\bshould depict\b", "depicts", line)
            line = re.sub(r"(?i)\bshould show\b", "shows", line)
            line = re.sub(r"(?i)\bshould use\b", "uses", line)
        if re.search(
            r"(?i)required diagrams and screenshots are essential|"
            r"once the figures are inserted|should be created by the student",
            line,
        ):
            line = (
                "The five required design figures are embedded in this report. "
                "Figure 5 is an illustrative testing-interface mockup, not evidence "
                "of a running system or completed test."
            )
        output.append(line)

    if in_action_summary:
        flush_action_summary()

    missing_markers = [
        f"[[GENERATED_FIGURE:{number}]]"
        for number in range(1, 6)
        if number not in inserted
    ]
    if missing_markers:
        output.extend(missing_markers)
    if has_figures_list or not any(
        re.match(r"(?i)^\s*#{1,6}\s*(?:\d+\.\s*)?list of figures", line)
        for line in output
    ):
        output.extend(["", figure_list_heading or "## List of Figures"])
        output.extend(
            f"{number}. Figure {number}: {caption}"
            for number, caption in enumerate(_FIGURE_CAPTIONS, 1)
        )
    return "\n".join(output)


def prepare_assignment_figures(
    content: str,
    instructions: str | None,
    assignment_title: str | None = None,
    packs: Sequence[AssignmentFigurePack] | None = None,
) -> tuple[str, dict[int, AssignmentFigure]]:
    registered_packs = packs if packs is not None else _ASSIGNMENT_FIGURE_PACKS
    for pack in registered_packs:
        if not pack.matches(content, instructions, assignment_title):
            continue
        prepared_content, definitions = pack.build(content, instructions)
        figures = render_figure_pack(definitions)
        prepared_content = _clean_resolved_figure_content(
            prepared_content,
            figures,
            instructions,
        )
        return prepared_content, figures
    return content, {}


_GENERATED_FIGURE_MARKER = re.compile(r"^\s*\[\[GENERATED_FIGURE:(\d+)\]\]\s*$")
_FIGURE_HEADING = re.compile(r"^\s*#{1,6}\s+")
_PLACEHOLDER_INSTRUCTION = re.compile(
    r"(?i)\bplaceholder\b.*\b(?:insert|create|draw|include|depict|display)\b|"
    r"\b(?:insert|create|draw|include)\b.*\bplaceholder\b"
)
_STALE_FIGURE_COMPLETION = re.compile(
    r"(?i)\bby\s+inserting\b[^.!?]*\bfigures?\b[^.!?]*[.!?]"
    r"|\b(?:once|when)\s+the\s+figures?\s+(?:are\s+)?(?:inserted|added|created)\b[^.!?]*[.!?]"
    r"|\b(?:figures?|diagrams?)\s+(?:still\s+)?(?:need|must|should)\s+to\s+be\s+"
    r"(?:inserted|added|created)\b[^.!?]*[.!?]"
)
_INSERTION_DIRECTIVE = re.compile(
    r"(?i)\b(?:insert|add|include|create|draw|place|attach)\b"
    r"|\b(?:should|must|needs? to)\s+be\s+"
    r"(?:inserted|added|included|created|drawn|placed|attached)\b"
)
_FIGURE_CAPTION_STOP_WORDS = {
    "a",
    "an",
    "and",
    "application",
    "as",
    "by",
    "diagram",
    "evidence",
    "figure",
    "for",
    "from",
    "in",
    "of",
    "or",
    "real",
    "screenshot",
    "the",
    "this",
    "to",
    "with",
}


def _is_redundant_figure_insertion(
    line: str,
    figure: AssignmentFigure,
) -> bool:
    visual_reference = re.search(
        r"(?i)\b(?:figure|image|illustration|diagram|mock[\s\-‐‑‒–—]*up|chart|visual)\b",
        line,
    )
    proposed_visual = re.search(
        r"(?i)\bproposed?\b|\b(?:to be|needs? to be|should be)\s+"
        r"(?:added|created|drawn|included|inserted|placed)\b",
        line,
    )
    if visual_reference and proposed_visual:
        return True
    if not _INSERTION_DIRECTIVE.search(line):
        return False
    if visual_reference:
        return True

    explicit_figure = re.search(r"(?i)\b(?:Figure|Fig\.?)\s+(\d+)\b", line)
    if explicit_figure and int(explicit_figure.group(1)) == figure.number:
        return True

    def caption_terms(text: str) -> set[str]:
        normalized = re.sub(r"(?i)\bmock[\s\-‐‑‒–—]+up\b", "mockup", text)
        normalized = re.sub(r"[\-‐‑‒–—]", " ", normalized)
        return {
            term
            for term in re.findall(r"[a-z0-9]+", normalized.casefold())
            if len(term) > 1 and term not in _FIGURE_CAPTION_STOP_WORDS
        }

    return len(caption_terms(line) & caption_terms(figure.caption)) >= 2


def _clean_resolved_figure_content(
    content: str,
    figures: dict[int, AssignmentFigure],
    instructions: str | None,
) -> str:
    lines = content.splitlines()
    embedded_figures = {
        int(match.group(1))
        for line in lines
        if (match := _GENERATED_FIGURE_MARKER.fullmatch(line))
        and int(match.group(1)) in figures
    }
    if not embedded_figures:
        return content
    content = _sync_generated_figure_list(content, figures)
    lines = content.splitlines()

    figure_for_line: list[int | None] = [None] * len(lines)
    section_start = 0
    for section_end in [
        *(
            index
            for index, line in enumerate(lines)
            if _FIGURE_HEADING.match(line)
        ),
        len(lines),
    ]:
        marker_positions = [
            (index, int(marker.group(1)))
            for index in range(section_start, section_end)
            if (marker := _GENERATED_FIGURE_MARKER.fullmatch(lines[index]))
            and int(marker.group(1)) in embedded_figures
        ]
        for index in range(section_start, section_end):
            if marker_positions:
                _, figure_number = min(
                    marker_positions,
                    key=lambda marker: abs(marker[0] - index),
                )
                figure_for_line[index] = figure_number
        section_start = section_end

    output: list[str] = []
    current_figure: int | None = None
    kept_screenshot_actions: set[int] = set()
    for index, line in enumerate(lines):
        marker = _GENERATED_FIGURE_MARKER.fullmatch(line)
        if marker:
            figure_number = int(marker.group(1))
            current_figure = figure_number if figure_number in embedded_figures else None
            output.append(line)
            continue
        if _FIGURE_HEADING.match(line):
            current_figure = figure_for_line[index]
        elif current_figure is None:
            current_figure = figure_for_line[index]

        if current_figure is not None:
            is_action = "student action required" in line.casefold()
            is_unverified_screenshot = (
                is_action
                and re.search(r"(?i)\b(?:screenshot|screen capture)\b", line)
            )
            explicit_action_figure = (
                re.search(r"(?i)\b(?:Figure|Fig\.?)\s+(\d+)\b", line)
                if is_action
                else None
            )
            if (
                explicit_action_figure
                and int(explicit_action_figure.group(1)) > max(figures)
            ):
                output.append(line)
                continue
            if is_unverified_screenshot:
                if not requires_genuine_screenshot(instructions, current_figure):
                    continue
                if current_figure in kept_screenshot_actions:
                    continue
                line = re.sub(
                    r"(?i)\b(Figure|Fig\.?)\s+\d+",
                    rf"\1 {current_figure}",
                    line,
                )
                kept_screenshot_actions.add(current_figure)
            elif (
                current_figure in figures
                and _is_redundant_figure_insertion(
                    line,
                    figures[current_figure],
                )
                and not (
                    re.search(r"(?i)\b(?:screenshot|screen capture|evidence)\b", line)
                    and requires_genuine_screenshot(instructions, current_figure)
                )
            ):
                continue
            elif is_action and re.search(
                r"(?i)\b(?:figure|image|illustration|diagram|chart)\b",
                line,
            ):
                continue
            elif (
                _PLACEHOLDER_INSTRUCTION.search(line)
            ):
                if (
                    re.search(r"(?i)\b(?:screenshot|screen capture)\b", line)
                    and requires_genuine_screenshot(instructions, current_figure)
                    and current_figure not in kept_screenshot_actions
                ):
                    output.append(
                        f"Student Action Required - Figure {current_figure} "
                        "(screenshot not captured): A generated illustration or "
                        "mockup is included, but it does not replace the required "
                        "genuine software screenshot. Capture and insert the "
                        "screenshot from the required software or account."
                    )
                    kept_screenshot_actions.add(current_figure)
                continue

        output.append(line)

    prepared_content = "\n".join(output)
    prepared_content = _move_list_of_figures_before_conclusion(prepared_content)
    if embedded_figures == set(figures):
        def replace_stale_completion(match: re.Match[str]) -> str:
            if "Student Action Required" in prepared_content:
                return (
                    "Generated figures are embedded in this document; any "
                    "Student Action Required evidence remains outstanding."
                )
            return (
                "The generated figures are embedded in this document. Generated "
                "illustrations and mockups are not genuine screenshots or evidence "
                "of external software activity."
            )

        prepared_content = _STALE_FIGURE_COMPLETION.sub(
            replace_stale_completion,
            prepared_content,
        )
        if not re.search(
            r"(?i)\bnot genuine screenshots?\b|\bnot evidence of\b",
            prepared_content,
        ):
            disclosure = (
                "Generated figures are illustrations or mockups, not genuine "
                "software screenshots or evidence of external software activity. "
                "Any explicitly required genuine screenshot must be supplied separately."
            )
            prepared_lines = prepared_content.splitlines()
            list_heading = next(
                (
                    index
                    for index, line in enumerate(prepared_lines)
                    if re.match(
                        r"(?i)^\s*#{1,6}\s*(?:\d+\.\s*)?list of figures\s*$",
                        line,
                    )
                ),
                None,
            )
            insertion = list_heading
            if insertion is None:
                insertion = next(
                    (
                        index
                        for index, line in enumerate(prepared_lines)
                        if _FIGURE_HEADING.match(line)
                        and re.search(
                            r"(?i)\bconclusions?\b",
                            line[_FIGURE_HEADING.match(line).end():],
                        )
                    ),
                    len(prepared_lines),
                )
            prepared_lines[insertion:insertion] = [disclosure, ""]
            prepared_content = "\n".join(prepared_lines)
    return prepared_content


def _move_list_of_figures_before_conclusion(content: str) -> str:
    lines = content.splitlines()
    list_start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(
                r"(?i)^\s*#{1,6}\s*(?:\d+\.\s*)?list of figures\s*$",
                _normalize_escaped_heading(line),
            )
        ),
        None,
    )
    if list_start is None:
        return content

    heading_match = re.match(r"^\s*(#+)", lines[list_start])
    heading_level = len(heading_match.group(1)) if heading_match else 2
    list_end = len(lines)
    for index in range(list_start + 1, len(lines)):
        match = _FIGURE_HEADING.match(lines[index])
        nested_conclusion = bool(
            match and re.search(r"(?i)\bconclusions?\b", lines[index][match.end():])
        )
        heading = re.match(r"^\s*(#+)", lines[index]) if match else None
        if match and (
            nested_conclusion or (heading and len(heading.group(1)) <= heading_level)
        ):
            list_end = index
            break
    list_section = lines[list_start:list_end]
    remaining = lines[:list_start] + lines[list_end:]

    conclusion_index = next(
        (
            index
            for index, line in enumerate(remaining)
            if (match := _FIGURE_HEADING.match(line))
            and re.search(r"(?i)\bconclusions?\b", line[match.end():])
        ),
        None,
    )
    if conclusion_index is None or list_start < conclusion_index:
        return content
    insertion = conclusion_index
    while insertion > 0 and not remaining[insertion - 1].strip():
        insertion -= 1
    return "\n".join(remaining[:insertion] + list_section + [""] + remaining[insertion:])


def _sync_generated_figure_list(
    content: str,
    figures: dict[int, AssignmentFigure],
) -> str:
    lines = content.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(
                r"(?i)^\s*#{1,6}\s*(?:\d+\.\s*)?list of figures\s*$",
                _normalize_escaped_heading(line),
            )
        ),
        None,
    )
    if start is None:
        return content

    heading = re.match(r"^\s*(#+)", lines[start])
    level = len(heading.group(1)) if heading else 2
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = _FIGURE_HEADING.match(lines[index])
        if not match:
            continue
        heading = re.match(r"^\s*(#+)", lines[index])
        nested_conclusion = bool(
            re.search(r"(?i)\bconclusions?\b", lines[index][match.end():])
        )
        if nested_conclusion or (heading and len(heading.group(1)) <= level):
            end = index
            break
    for index in range(start + 1, end):
        line = lines[index]
        if line.strip().startswith("|"):
            cells = _split_cells(line)
            figure_cell = next(
                (
                    cell_index
                    for cell_index, cell in enumerate(cells)
                    if (match := re.search(r"(?i)\b(?:Figure|Fig\.?)\s+(\d+)\b", cell))
                    and int(match.group(1)) in figures
                ),
                None,
            )
            if figure_cell is not None:
                number_match = re.search(
                    r"(?i)\b(?:Figure|Fig\.?)\s+(\d+)\b",
                    cells[figure_cell],
                )
                number = int(number_match.group(1))
                if figure_cell + 1 < len(cells):
                    cells[figure_cell + 1] = figures[number].caption
                    cells[figure_cell] = f"Figure {number}"
                else:
                    cells[figure_cell] = f"Figure {number}: {figures[number].caption}"
                lines[index] = "| " + " | ".join(cells) + " |"
            continue

        list_match = re.match(
            r"^(\s*(?:[-*+]\s+|\d+[.)]\s+)?)(?:Figure|Fig\.?)\s+"
            r"(\d+)\s*[:.)\-–—]\s*.*$",
            line,
            re.IGNORECASE,
        )
        if list_match:
            prefix, raw_number = list_match.groups()
            number = int(raw_number)
            if number in figures:
                lines[index] = (
                    f"{prefix}Figure {number}: {figures[number].caption}"
                )
    return "\n".join(lines)


def _build_student_management_figures(
    content: str,
    instructions: str | None,
) -> tuple[str, Sequence[FigureDefinition]]:
    actors = _parse_actors(content)
    entities, relationships = _parse_entities(content)
    render_arguments: tuple[tuple[object, ...], ...] = (
        (),
        (actors,),
        (entities, relationships),
        (),
        (),
    )
    definitions = [
        FigureDefinition(number, caption, renderer, arguments)
        for number, (caption, renderer, arguments) in enumerate(
            zip(_FIGURE_CAPTIONS, _RENDERERS, render_arguments, strict=True),
            start=1,
        )
    ]
    return _resolve_figure_markers(content, instructions), definitions


register_assignment_figure_pack(
    AssignmentFigurePack(
        matches=_needs_student_management_figures,
        build=_build_student_management_figures,
    )
)
