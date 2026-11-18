import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException
from groq import APIStatusError

from app.core.config import settings
from app.services.assignment_ai import GROQ_MODEL, create_assignment_suggestion
from app.services.assignment_evidence import mark_unverified_screenshot_placeholders


class AssignmentAITests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Mock()
        self.completions = self.client.chat.completions
        self.kwargs = {
            "title": "Writing assignment",
            "instructions": "Explain the supplied concept.",
            "course": "Writing Studies",
            "attachments": [],
            "current_draft": None,
            "action": "generate",
            "length": "standard",
            "style": "academic",
            "selected_text": None,
            "instruction": None,
        }

    def test_request_uses_active_groq_model_and_returns_generated_content(self) -> None:
        self.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="A grounded draft response.")
                )
            ]
        )
        with (
            patch.object(settings, "groq_api_key", "test-key"),
            patch("groq.Groq", return_value=self.client) as groq_client,
        ):
            result = create_assignment_suggestion(**self.kwargs)

        self.assertEqual(result, "A grounded draft response.")
        groq_client.assert_called_once_with(
            api_key="test-key",
            timeout=60,
            max_retries=1,
        )
        self.completions.create.assert_called_once()
        self.assertEqual(
            self.completions.create.call_args.kwargs["model"],
            "openai/gpt-oss-120b",
        )
        self.assertEqual(GROQ_MODEL, "openai/gpt-oss-120b")

    def test_ordinary_assignment_regeneration_builds_prompt_without_project_instructions(self) -> None:
        self.kwargs.update(
            action="rewrite",
            current_draft="An existing ordinary assignment draft.",
            instruction="Improve clarity.",
        )
        self.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="A clearer draft."))
            ]
        )

        with (
            patch.object(settings, "groq_api_key", "test-key"),
            patch("groq.Groq", return_value=self.client),
        ):
            result = create_assignment_suggestion(**self.kwargs)

        prompt = self.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertEqual(result, "A clearer draft.")
        self.assertIn("Rewrite the supplied student draft", prompt)
        self.assertIn("Improve clarity.", prompt)
        self.assertNotIn("action-oriented Microsoft Project practical", prompt)

    def test_microsoft_project_regeneration_keeps_schedule_requirements(self) -> None:
        self.kwargs.update(
            title="Microsoft Project Practical",
            instructions=(
                "Create a semester project in Microsoft Project with a start date, "
                "durations, a Gantt Chart, and milestones."
            ),
            current_draft="Existing semester project schedule.",
            action="rewrite",
            instruction="Improve this schedule.",
        )
        self.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="A revised project schedule.")
                )
            ]
        )

        with (
            patch.object(settings, "groq_api_key", "test-key"),
            patch("groq.Groq", return_value=self.client),
        ):
            result = create_assignment_suggestion(**self.kwargs)

        prompt = self.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertEqual(result, "A revised project schedule.")
        self.assertIn("Rewrite the supplied student draft", prompt)
        self.assertIn("action-oriented Microsoft Project practical", prompt)
        self.assertIn("8-10 actual non-milestone task rows", prompt)
        self.assertIn(
            "ID | Task Name | Duration | Start | Finish | Predecessors | Milestone",
            prompt,
        )

    def test_selected_passage_rewrite_does_not_add_full_schedule_instructions(self) -> None:
        self.kwargs.update(
            title="Microsoft Project Practical",
            instructions=(
                "Create a semester project in Microsoft Project with a start date, "
                "durations, a Gantt Chart, and milestones."
            ),
            current_draft="Existing project schedule.",
            action="rewrite",
            selected_text="A single selected sentence.",
            instruction="Improve clarity.",
        )
        self.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="A clearer selected sentence.")
                )
            ]
        )

        with (
            patch.object(settings, "groq_api_key", "test-key"),
            patch("groq.Groq", return_value=self.client),
        ):
            result = create_assignment_suggestion(**self.kwargs)

        prompt = self.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertEqual(result, "A clearer selected sentence.")
        self.assertIn("Rewrite only the selected passage", prompt)
        self.assertNotIn("action-oriented Microsoft Project practical", prompt)

    def test_lab_assignment_prompt_requires_deliverables_and_preserves_duplicate_numbering(self) -> None:
        self.kwargs.update(
            title="Software Project Management Lab",
            course="Software Project Management",
            instructions=(
                "Lab Task 1: Install Microsoft Project using the Office Deployment Tool "
                "and Command Prompt.\n"
                "Lab Task 1: Create a semester project in Microsoft Project with "
                "appropriate tasks, durations, dependencies, and milestones.\n"
                "Lab Task 2: Create a Trello workspace and board with lists, cards, "
                "labels, due dates, and checklists."
            ),
        )
        self.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Completed report."))]
        )

        with (
            patch.object(settings, "groq_api_key", "test-key"),
            patch("groq.Groq", return_value=self.client),
        ):
            result = create_assignment_suggestion(**self.kwargs)

        self.assertEqual(result, "Completed report.")
        request = self.completions.create.call_args.kwargs
        prompt = request["messages"][1]["content"]
        system_prompt = request["messages"][0]["content"]
        normalized_prompt = " ".join(prompt.split())
        normalized_system_prompt = " ".join(system_prompt.split())
        self.assertIn("Lab Task 1: Install Microsoft Project", normalized_prompt)
        self.assertIn("Lab Task 1: Create a semester project", normalized_prompt)
        self.assertIn("Lab Task 2: Create a Trello workspace", normalized_prompt)
        self.assertIn("answer each in the source order", normalized_prompt)
        self.assertIn("Preserve the source's numbering exactly", normalized_prompt)
        self.assertIn("clearly distinguish their occurrences", normalized_prompt)
        self.assertIn(
            "actual proposed project schedules with task names, durations, dependencies, and milestones",
            normalized_prompt,
        )
        self.assertIn(
            "lists, concrete cards, descriptions, labels, due dates, and checklists",
            normalized_prompt,
        )
        self.assertIn("end-to-end procedure with commands/configuration", normalized_prompt)
        self.assertIn("professional assignment report", normalized_prompt)
        self.assertIn("Never claim to have installed", normalized_prompt)
        self.assertIn("rather than restating the task", normalized_system_prompt)

    def test_exact_microsoft_project_practical_requests_completed_schedule_and_csv(self) -> None:
        instructions = """1. Open Microsoft Project.
2. Create a new blank project.
3. Enter a project name such as Semester Project.
4. Set the project start date.
5. Create at least 8–10 tasks.
6. Enter durations.
7. Set start and finish dates.
8. Arrange tasks logically.
9. Add milestones.
10. View the Gantt Chart.
11. Save the project file."""
        self.kwargs.update(
            title="Microsoft Project Practical",
            course="Software Project Management",
            instructions=instructions,
        )
        generated_schedule = """# Semester Project — Student Portal
Project start date: 2026-11-09 (assumption; Monday-Friday calendar).
| ID | Task Name | Duration | Start | Finish | Predecessors | Milestone |
|---|---|---|---|---|---|---|
| 1 | Define project scope | 2d | 2026-11-09 | 2026-11-10 | None | No |
| 2 | Gather requirements | 3d | 2026-11-11 | 2026-11-13 | 1 | No |
| 3 | Draft requirements specification | 2d | 2026-11-16 | 2026-11-17 | 2 | No |
| 4 | Requirements approved | 0d | 2026-11-18 | 2026-11-18 | 3 | Yes |
| 5 | Design architecture | 3d | 2026-11-18 | 2026-11-20 | 4 | No |
| 6 | Design approved | 0d | 2026-11-23 | 2026-11-23 | 5 | Yes |
| 7 | Implement backend | 5d | 2026-11-23 | 2026-11-27 | 6 | No |
| 8 | Implement user interface | 5d | 2026-11-23 | 2026-11-27 | 6 | No |
| 9 | Integrate modules | 2d | 2026-11-30 | 2026-12-01 | 7, 8 | No |
| 10 | System testing | 3d | 2026-12-02 | 2026-12-04 | 9 | No |
| 11 | User acceptance testing | 2d | 2026-12-07 | 2026-12-08 | 10 | No |
| 12 | Prepare release package | 1d | 2026-12-09 | 2026-12-09 | 11 | No |
| 13 | Semester project complete | 0d | 2026-12-10 | 2026-12-10 | 12 | Yes |

## Gantt Chart
| Task | Nov 9 | Nov 16 | Nov 23 | Nov 30 | Dec 7 |
|---|---|---|---|---|---|
| Define project scope | ██ | | | | |
| Gather requirements | | ██ | | | |
| Implement backend | | | ██ | | |
| System testing | | | | | ██ |

## Remaining Microsoft Project Actions
- Import the generated CSV and map the schedule columns.
- Confirm the project calendar, review the Gantt Chart, and save the actual .mpp file.
ClassMate AI generated a schedule CSV, not an .mpp file, and did not operate Microsoft Project.
"""
        self.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=generated_schedule))]
        )

        with (
            patch.object(settings, "groq_api_key", "test-key"),
            patch("groq.Groq", return_value=self.client),
        ):
            result = create_assignment_suggestion(**self.kwargs)

        prompt = " ".join(
            self.completions.create.call_args.kwargs["messages"][1]["content"].split()
        )
        self.assertIn(" ".join(instructions.split()), prompt)
        self.assertIn("action-oriented Microsoft Project practical", prompt)
        self.assertIn("8-10 actual non-milestone task rows", prompt)
        self.assertIn(
            "ID | Task Name | Duration | Start | Finish | Predecessors | Milestone",
            prompt,
        )
        self.assertIn("weekly text-bar chart", prompt)
        self.assertIn("generated the schedule CSV, not an .mpp file", prompt)
        self.assertIn("Define project scope", result)
        self.assertIn("2026-11-09", result)
        self.assertIn("Implement backend", result)
        self.assertIn("| 9 | Integrate modules | 2d", result)
        self.assertIn("Semester project complete", result)
        self.assertIn("## Gantt Chart", result)
        self.assertIn("## Remaining Microsoft Project Actions", result)
        self.assertIn("Import the generated CSV", result)
        self.assertIn("not an .mpp file", result)

    def test_screenshot_placeholder_is_marked_as_unverified_student_action(self) -> None:
        self.kwargs["instructions"] = (
            "Create a Trello board and include a screenshot in Figure 7."
        )
        self.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            "Figure 7: Trello workspace overview showing the newly "
                            "created workspace and board."
                        )
                    )
                )
            ]
        )

        with (
            patch.object(settings, "groq_api_key", "test-key"),
            patch("groq.Groq", return_value=self.client),
        ):
            result = create_assignment_suggestion(**self.kwargs)

        request_prompt = self.completions.create.call_args.kwargs["messages"][1]["content"]
        normalized_prompt = " ".join(request_prompt.split())
        self.assertIn(
            "Screenshot requirements detected in the teacher instructions: Yes",
            normalized_prompt,
        )
        self.assertIn("preserve every figure number exactly", normalized_prompt)
        self.assertIn("Do not create fake images", normalized_prompt)
        self.assertIn("Student Action Required - Figure 7", result)
        self.assertIn("screenshot not captured", result)
        self.assertIn("Capture a genuine screenshot", result)
        self.assertIn("This placeholder is not evidence.", result)
        self.assertNotIn("Figure 7: Trello workspace overview", result)

    def test_screenshot_figure_number_uses_teacher_figure_through_generation(self) -> None:
        self.kwargs["instructions"] = (
            "Include a screenshot as Figure 6 showing the task list and Gantt Chart."
        )
        self.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            "Student Action Required — Screenshot (not captured): "
                            "Figure 1 – Placeholder for the screenshot of the task "
                            "list and Gantt Chart."
                        )
                    )
                )
            ]
        )

        with (
            patch.object(settings, "groq_api_key", "test-key"),
            patch("groq.Groq", return_value=self.client),
        ):
            result = create_assignment_suggestion(**self.kwargs)

        self.assertIn("Student Action Required - Figure 6", result)
        self.assertIn("task list and Gantt Chart", result)
        self.assertIn("This placeholder is not evidence.", result)
        self.assertNotIn("Figure 1", result)
        self.assertEqual(
            mark_unverified_screenshot_placeholders(result, self.kwargs["instructions"]),
            result,
        )

    def test_unknown_screenshot_number_is_unspecified_not_invented(self) -> None:
        result = mark_unverified_screenshot_placeholders(
            "Figure 1 – Placeholder for the screenshot of the task list.",
            "Include a screenshot of the task list.",
        )
        self.assertIn("Figure unspecified (screenshot not captured)", result)
        self.assertNotIn("Figure 1", result)

    def test_provider_error_logs_safe_metadata_but_not_key_or_response_body(self) -> None:
        secret = "test-groq-secret"
        body = {
            "error": {
                "message": f"Invalid model; echoed credential {secret}",
                "type": "invalid_request_error",
                "code": "model_decommissioned",
            }
        }
        request = httpx.Request(
            "POST",
            "https://api.groq.com/openai/v1/chat/completions",
        )
        response = httpx.Response(
            400,
            request=request,
            headers={"x-request-id": "req-test-123"},
            json=body,
        )
        self.completions.create.side_effect = APIStatusError(
            "Bad Request",
            response=response,
            body=body,
        )

        with (
            patch.object(settings, "groq_api_key", secret),
            patch("groq.Groq", return_value=self.client),
            self.assertLogs("app.services.assignment_ai", level="WARNING") as logs,
        ):
            with self.assertRaises(HTTPException) as raised:
                create_assignment_suggestion(**self.kwargs)

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(
            raised.exception.detail,
            "The AI service could not complete this request. Try again later.",
        )
        output = "\n".join(logs.output)
        self.assertIn("status=400", output)
        self.assertIn("error_code=model_decommissioned", output)
        self.assertIn("request_id=req-test-123", output)
        self.assertIn(GROQ_MODEL, output)
        self.assertNotIn(secret, output)
        self.assertNotIn(body["error"]["message"], output)


if __name__ == "__main__":
    unittest.main()
