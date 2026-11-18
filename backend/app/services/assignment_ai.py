import logging
from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.services.assignment_evidence import (
    has_screenshot_requirement,
    mark_unverified_screenshot_placeholders,
)

logger = logging.getLogger(__name__)
GROQ_MODEL = "openai/gpt-oss-120b"


def create_assignment_suggestion(
    *,
    title: str,
    instructions: str | None,
    course: str | None,
    attachments: list[dict[str, Any]],
    current_draft: str | None,
    action: str,
    length: str,
    style: str,
    selected_text: str | None,
    instruction: str | None,
) -> str:
    if not settings.groq_api_key.strip():
        raise HTTPException(
            status_code=503,
            detail="AI generation is not configured. Add GROQ_API_KEY to backend/.env.",
        )

    try:
        from groq import APIConnectionError, APIStatusError, Groq, RateLimitError
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="The Groq client is unavailable. Install backend requirements and try again.",
        ) from exc

    project_schedule_required = bool(
        instructions
        and "microsoft project" in instructions.casefold()
        and any(
            phrase in instructions.casefold()
            for phrase in ("start date", "durations", "gantt chart", "milestones")
        )
    )
    project_schedule_instructions = ""
    if project_schedule_required and not selected_text:
        project_schedule_instructions = """
This is an action-oriented Microsoft Project practical. Deliver a completed proposed
project plan, not directions for entering one. Include a named project and an explicit
start date; if the teacher did not specify the date, label your chosen date as an
assumption. Provide 8-10 actual non-milestone task rows plus appropriate zero-duration
milestone rows. Give every row a stable sequential ID, meaningful task name, duration,
start and finish dates, predecessor IDs (or None), and milestone flag. Calculate dates
consistently from the durations and dependencies, assume a Monday-Friday working
calendar unless stated otherwise, and explicitly label that assumption. Do not output
empty/fake dates or generic labels like Task 1. Include one Markdown schedule table
with exactly these columns so it can produce a Microsoft Project-importable CSV:
ID | Task Name | Duration | Start | Finish | Predecessors | Milestone
Use YYYY-MM-DD dates, durations such as 5d, predecessor IDs separated by commas,
and Yes/No for the milestone flag. Also give a readable Gantt representation based on
the schedule (for example a weekly text-bar chart), then list only the remaining actions
the student must perform in Microsoft Project, such as importing the CSV, confirming
the project calendar, reviewing the chart, and saving an actual .mpp file. Clearly state
that ClassMate generated the schedule CSV, not an .mpp file, and did not operate the
student's Microsoft Project installation.
"""

    if selected_text:
        task = (
            "Rewrite only the selected passage. Return only the replacement passage, "
            "without commentary, and do not rewrite other parts of the assignment."
        )
    elif action == "generate":
        screenshot_requirement_status = (
            "Yes" if has_screenshot_requirement(instructions) else "No"
        )
        task = f"""Complete the assignment itself; do not summarize, paraphrase, or turn the
instructions into advice about what the student should do. First identify every task,
subtask, and deliverable, then answer each in the source order. Preserve the source's
numbering exactly. If task numbers are duplicated or ambiguous, retain them and clearly
distinguish their occurrences rather than silently renumbering them.

Provide the requested work, not just a description of it: include actual proposed
project schedules with task names, durations, dependencies, and milestones; for Trello,
specify the workspace/board, lists, concrete cards, descriptions, labels, due dates,
and checklists; include working code and run instructions, calculations with formulas
and working, and relevant tables or other requested content, as applicable. For
installation tasks, give concrete prerequisites and an end-to-end procedure with
commands/configuration where appropriate.
For practical actions that require external software, accounts, or access, provide
usable instructions and ready-to-enter content, then clearly separate what this
response completed from what the student must do. Never claim to have installed
software, created accounts, configured external services, run experiments, or captured
screenshots unless that action actually occurred.

Screenshot requirements detected in the teacher instructions:
{screenshot_requirement_status}
If yes, preserve every figure number exactly and identify each unavailable screenshot
as "Student Action Required." Include a short caption describing the required view
and how to capture it. This service cannot operate Microsoft Project, Trello, or the
student's accounts and has not captured screenshots. Do not create fake images or
present descriptions/placeholders as completed evidence.

Present the solution as a professional assignment report unless the teacher explicitly
requires another format. Include a title, unfilled student-information placeholders
where details are missing, an introduction, task-by-task solutions, the requested
practical content, student actions still required, results where supported, and a
conclusion. Use Markdown headings, tables, lists, and fenced code blocks where they
make the deliverables clearer."""
    else:
        task = "Rewrite the supplied student draft according to the requested instruction."

    attachment_list = "\n".join(
        f"- {item.get('title') or 'Untitled material'} "
        f"({item.get('type') or 'material'}): {item.get('url') or 'link not provided'}"
        for item in attachments
        if isinstance(item, dict)
    ) or "No attachments were provided."
    prompt = f"""Assignment title: {title}
Course: {course or "Not provided"}
Assignment instructions: {instructions or "Not provided"}
Classroom attachment metadata (titles and links only; contents are not available):
{attachment_list}
Current student draft: {current_draft or "No draft has been saved yet."}
Selected passage: {selected_text or "None"}
Student's requested change: {instruction or "None"}
Requested length: {length}
Writing style: {style}

{task}

{project_schedule_instructions}

Treat the assignment instructions as the specification. Use relevant general knowledge
to complete the requested work, but label proposed/example data and assumptions clearly
and do not present them as teacher-provided facts or real-world results. Do not invent
citations, quotations, sources, research findings, measured results, or personal/student
details. If essential information is missing, state the limitation and make any
reasonable example assumptions explicit. Attachment links and titles are metadata only;
do not claim to have opened or read attachment contents. Return only the proposed
assignment text."""

    client = Groq(api_key=settings.groq_api_key.strip(), timeout=60, max_retries=1)
    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a careful academic assignment assistant. Follow the "
                        "teacher's requirements, produce the requested deliverables "
                        "rather than restating the task, preserve source numbering, "
                        "separate proposed content from real-world actions, and never "
                        "fabricate evidence, citations, or student details."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=4_000,
        )
    except RateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail="The AI service is busy. Wait a moment and try again.",
        ) from exc
    except APIStatusError as exc:
        provider_error = exc.body.get("error", {}) if isinstance(exc.body, dict) else {}
        error_code = provider_error.get("code") if isinstance(provider_error, dict) else None
        error_type = provider_error.get("type") if isinstance(provider_error, dict) else None
        request_id = exc.response.headers.get("x-request-id")
        logger.warning(
            "Groq chat completion failed: model=%s status=%s error_type=%s "
            "error_code=%s request_id=%s",
            GROQ_MODEL,
            exc.status_code,
            error_type,
            error_code,
            request_id,
        )
        raise HTTPException(
            status_code=502,
            detail="The AI service could not complete this request. Try again later.",
        ) from exc
    except APIConnectionError as exc:
        logger.warning(
            "Groq chat completion connection failed: model=%s error_type=%s",
            GROQ_MODEL,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the AI service. Check the backend connection and try again.",
        ) from exc

    content = completion.choices[0].message.content
    if not content or not content.strip():
        raise HTTPException(status_code=502, detail="The AI service returned an empty suggestion.")
    return mark_unverified_screenshot_placeholders(content.strip(), instructions)
