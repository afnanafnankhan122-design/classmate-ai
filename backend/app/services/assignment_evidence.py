import re


_SCREENSHOT_REQUIREMENT = re.compile(
    r"\b(?:screenshots?|screen shots?|screen captures?|"
    r"capture (?:a |the )?(?:screen|interface)|"
    r"take (?:a |the )?(?:screen|interface)|"
    r"visual evidence)\b",
    re.IGNORECASE,
)
_FIGURE_REFERENCE = re.compile(r"\b(?:Figure|Fig\.?)\s+(\d+[A-Za-z]?)\b", re.IGNORECASE)
_FIGURE_CAPTION = re.compile(
    r"^\s*(?:\*\*)?(?:Figure|Fig\.?)\s+(\d+[A-Za-z]?)\s*[:.)\-–—]\s*(.+?)\s*(?:\*\*)?\s*$",
    re.IGNORECASE,
)
_FIGURE_CAPTION_ANYWHERE = re.compile(
    r"\b(?:Figure|Fig\.?)\s+(\d+[A-Za-z]?)\s*[:.)\-–—]\s*(.+)",
    re.IGNORECASE,
)
_ACTION_FIGURE_CAPTION = re.compile(
    r"^(?:Figure|Fig\.?)\s+(\d+[A-Za-z]?|unspecified)\s+"
    r"\(screenshot not captured\):\s*(.+)$",
    re.IGNORECASE,
)
_SCREENSHOT_CUE = re.compile(
    r"\b(?:screenshot|screen shot|screen capture|screen-capture|"
    r"Trello|Microsoft Project|workspace overview|board overview|"
    r"application interface|software interface)\b",
    re.IGNORECASE,
)
_ACTION_PREFIX = "Student Action Required - "


def has_screenshot_requirement(instructions: str | None) -> bool:
    return bool(instructions and _SCREENSHOT_REQUIREMENT.search(instructions))


def requires_genuine_screenshot(
    instructions: str | None,
    figure_number: int | str | None = None,
) -> bool:
    if not instructions:
        return False
    for line in instructions.splitlines():
        if not _SCREENSHOT_REQUIREMENT.search(line):
            continue
        referenced_figures = {
            match.group(1).casefold()
            for match in _FIGURE_REFERENCE.finditer(line)
        }
        if (
            figure_number is not None
            and referenced_figures
            and str(figure_number).casefold() not in referenced_figures
        ):
            continue
        if re.search(
            r"\b(?:do not|don't|never|must not|cannot|should not)\b"
            r".{0,80}\b(?:invent|fabricate|fake|claim|create)\b"
            r".{0,50}\b(?:screenshots?|screen captures?)\b",
            line,
            re.IGNORECASE,
        ):
            continue
        if re.search(
            r"\b(?:screenshots?|screen captures?)\b.{0,50}"
            r"\b(?:or|and/or)\b.{0,30}"
            r"\b(?:illustrative|generated|sample|mock[- ]?up|diagram|image|illustration)\b",
            line,
            re.IGNORECASE,
        ):
            continue
        if re.search(
            r"\b(?:illustrative|generated|sample|mock[- ]?up|diagram|image|illustration)\b"
            r".{0,30}\b(?:or|and/or)\b.{0,30}\b(?:screenshots?|screen captures?)\b",
            line,
            re.IGNORECASE,
        ):
            continue
        return True
    return False


def mark_unverified_screenshot_placeholders(
    content: str,
    instructions: str | None = None,
) -> str:
    screenshot_required = has_screenshot_requirement(instructions)
    instruction_lines = [
        line.strip()
        for line in (instructions or "").splitlines()
        if _SCREENSHOT_REQUIREMENT.search(line)
    ]
    output_lines: list[str] = []
    seen_figures: set[str] = set()
    all_instruction_figures = {
        match.group(1).casefold(): match.group(1)
        for match in _FIGURE_REFERENCE.finditer(instructions or "")
    }
    instruction_figures = {
        match.group(1).casefold(): match.group(1)
        for line in instruction_lines
        for match in _FIGURE_REFERENCE.finditer(line)
    }
    if not instruction_figures and len(all_instruction_figures) == 1:
        instruction_figures = all_instruction_figures

    def verified_figure_number(generated_number: str | None) -> str:
        if len(instruction_figures) == 1:
            return next(iter(instruction_figures.values()))
        if generated_number and generated_number.casefold() in instruction_figures:
            return instruction_figures[generated_number.casefold()]
        return "unspecified"

    def caption_with_capture_guidance(caption: str) -> str:
        clean_caption = caption.rstrip()
        if clean_caption and clean_caption[-1] not in ".!?":
            clean_caption += "."
        return (
            f"{clean_caption} Capture a genuine screenshot in the required software "
            "or account, then insert it here. This placeholder is not evidence."
        )

    for line in content.splitlines():
        stripped_line = line.strip()
        already_action = stripped_line.startswith(_ACTION_PREFIX)
        candidate = stripped_line[len(_ACTION_PREFIX) :] if already_action else stripped_line
        figure_caption = _FIGURE_CAPTION.match(candidate)
        embedded_caption = _FIGURE_CAPTION_ANYWHERE.search(candidate)
        action_caption = _ACTION_FIGURE_CAPTION.match(candidate)
        has_screenshot_cue = bool(_SCREENSHOT_CUE.search(candidate))

        if already_action and action_caption:
            generated_number, caption = action_caption.groups()
            number = (
                verified_figure_number(generated_number)
                if generated_number.casefold() != "unspecified"
                else verified_figure_number(None)
            )
            seen_figures.add(number.casefold())
            output_lines.append(
                f"{_ACTION_PREFIX}Figure {number} (screenshot not captured): "
                f"{caption}"
            )
        elif figure_caption and (screenshot_required or has_screenshot_cue):
            generated_number, caption = figure_caption.groups()
            number = verified_figure_number(generated_number)
            seen_figures.add(number.casefold())
            output_lines.append(
                f"{_ACTION_PREFIX}Figure {number} (screenshot not captured): "
                f"{caption_with_capture_guidance(caption)}"
            )
        elif already_action and (has_screenshot_cue or embedded_caption):
            generated_number = embedded_caption.group(1) if embedded_caption else None
            number = verified_figure_number(generated_number)
            caption = embedded_caption.group(2) if embedded_caption else candidate
            seen_figures.add(number.casefold())
            output_lines.append(
                f"{_ACTION_PREFIX}Figure {number} (screenshot not captured): "
                f"{caption_with_capture_guidance(caption)}"
            )
        elif has_screenshot_cue and _SCREENSHOT_REQUIREMENT.search(candidate):
            embedded_number = embedded_caption.group(1) if embedded_caption else None
            number = verified_figure_number(embedded_number)
            caption = embedded_caption.group(2) if embedded_caption else candidate
            seen_figures.add(number.casefold())
            output_lines.append(
                f"{_ACTION_PREFIX}Figure {number} (screenshot not captured): "
                f"{caption_with_capture_guidance(caption)}"
            )
        else:
            output_lines.append(line)

    if instruction_lines:
        for folded_number, number in instruction_figures.items():
            if folded_number not in seen_figures:
                instruction_line = next(
                    (
                        line.strip()
                        for line in instruction_lines
                        if _FIGURE_REFERENCE.search(line)
                    ),
                    "The assignment requires a screenshot.",
                )
                output_lines.extend(
                    [
                        "",
                        f"{_ACTION_PREFIX}Figure {number} (screenshot not captured): "
                        f"{caption_with_capture_guidance(instruction_line)}",
                    ]
                )

        if not instruction_figures and not any(
            line.strip().startswith(_ACTION_PREFIX) for line in output_lines
        ):
            output_lines.extend(
                [
                    "",
                    f"{_ACTION_PREFIX}Figure unspecified (screenshot not captured): "
                    f"{caption_with_capture_guidance(' '.join(instruction_lines))}",
                ]
            )

    return "\n".join(output_lines).strip()
