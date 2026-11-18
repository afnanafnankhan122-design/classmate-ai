from io import BytesIO
import csv
from datetime import UTC, datetime, timedelta
from io import StringIO
import re
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import pymupdf
from PIL import Image

from app.api.routes.auth import get_current_user
from app.database.base import Base
from app.database.dependencies import get_db
from app.core.auth_security import auth_rate_limiter
from app.main import app
from app.models.assignment import Assignment, AssignmentDraftVersion, AssignmentExport
from app.models.approval import Approval
from app.models.course import Course
from app.models.licensing import License, LicensingPolicy, Plan
from app.models.user import User
from app.services.assignment_documents import (
    _display_assignment_title,
    _plain_lines,
)
from app.services.assignment_evidence import requires_genuine_screenshot
from app.services.assignment_figures import (
    AssignmentFigureGenerationError,
    AssignmentFigurePack,
    FigureDefinition,
    _figure_3,
    _parse_entities,
    prepare_assignment_figures,
    register_assignment_figure_pack,
    render_figure_pack,
)


_SMS_FIGURE_INSTRUCTIONS = """Additional Instructions: Pictures and Diagrams (Mandatory)
Include relevant pictures, illustrations, and diagrams throughout the assignment.
The assignment is for a Student Management System. Include a Student Management
System high-level illustration, a Use Case Diagram, an ERD, a three-tier System
Architecture, a sample Testing Interface, and a List of Figures.
"""
_SMS_FIGURE_DRAFT = """# Student Management System Design

## 1. Introduction
A Student Management System organizes student, course, enrollment, grade, and attendance information.
Student Action Required - Figure 1 (screenshot not captured): Student Management System - High-level overview.
*Placeholder - insert an SMS overview illustration showing the user groups and modules.*
**Proposed illustration:** create another high-resolution diagram of the SMS user groups and modules.

## 2. System Design
| Actor | Primary Use Cases |
|---|---|
| Administrator | Manage student records, Create/modify courses, Generate reports, Assign roles |
| Teacher | Record attendance, Enter grades, View class roster, Upload resources |
| Student | Register for courses, View grades, Update personal profile, Access materials |
| Parent/Guardian | View student progress, Receive notifications, Access reports |

Student Action Required - Figure 1 (screenshot not captured): Use Case Diagram - Actors and Interactions.
*Placeholder - insert a use-case diagram with the defined actors and interactions.*

## 3. Database Design
| Entity | Primary Key | Notable Attributes (examples) |
|---|---|---|
| Student | student_id | first_name, last_name, dob, email, enrollment_date |
| Course | course_id | course_name, description, credits |
| Enrollment | enrollment_id | student_id (FK), course_id (FK), term, status |
| Teacher | teacher_id | first_name, last_name, department, email |
| Teaching_Assign | assign_id | teacher_id (FK), course_id (FK), term |
| Grade | grade_id | enrollment_id (FK), grade_value, date_recorded |
| Attendance | attendance_id | enrollment_id (FK), date, status |

*Relationships to depict:*
- **Student** 1-* **Enrollment** (one student can have many enrollments)
- **Course** 1-* **Enrollment** (one course can have many enrollments)
- **Teacher** 1-* **Teaching_Assign** (one teacher can teach many courses)
- **Course** 1-* **Teaching_Assign** (a course can have many teachers)
- **Enrollment** 1-1 **Grade** (each enrollment may have one grade)
- **Enrollment** 1-* **Attendance** (multiple attendance records per enrollment)

Student Action Required - Figure 1 (screenshot not captured): Entity-Relationship Diagram - Database Schema.
*Placeholder - insert an ERD (created with MySQL Workbench, dbdiagram.io, or a similar tool) that includes the following entities and key attributes: ?*

## 4. System Architecture
Student Action Required - Figure 1 (screenshot not captured): System Architecture - Presentation, Business Logic, Data Layers.
*Placeholder - insert an architecture diagram showing the three system layers.*

## 5. Testing
Student Action Required - Figure 1 (screenshot not captured): Testing Interface - Example Test Case Entry.
Student Action Required - Figure 1 (screenshot not captured): Placeholder for a test-case interface screenshot.
*Placeholder - insert a screenshot or mockup of the test-case interface.*
**Create a testing mock-up** showing the Test ID, Description, Steps, and Expected Result fields.
The interface is an illustrative design only.
*Insert a mock-up of a test-case management screen with the listed test fields.*

## 6. List of Figures
| Figure | Caption |
|---|---|
| Figure 1 | Student Management System - High-level overview |
| Figure 2 | Use Case Diagram - Actors and Interactions |
| Figure 3 | Entity-Relationship Diagram - Database Schema |
| Figure 4 | System Architecture - Presentation, Business Logic, Data Layers |
| Figure 5 | Testing Interface - Example Test Case Entry |

## 7. Conclusion
By inserting the indicated figures—created with standard modelling tools—the assignment will satisfy the mandatory requirement for pictures, diagrams, and a list of figures, and will be ready for final submission.
"""
_SMS_FIGURE_RELATIONSHIP_BLOCK = """*Relationships to depict:*
- **Student** 1-* **Enrollment** (one student can have many enrollments)
- **Course** 1-* **Enrollment** (one course can have many enrollments)
- **Teacher** 1-* **Teaching_Assign** (one teacher can teach many courses)
- **Course** 1-* **Teaching_Assign** (a course can have many teachers)
- **Enrollment** 1-1 **Grade** (each enrollment may have one grade)
- **Enrollment** 1-* **Attendance** (multiple attendance records per enrollment)"""
_SAVED_SMS_RELATIONSHIPS = """*Relationships (crow’s‑foot notation):*

- Student\u202f1\u202f—\u202f*\u202fEnrollment
- Course\u202f1\u202f—\u202f*\u202fEnrollment
- Teacher\u202f1\u202f—\u202f*\u202fTeaching_Assign
- Course\u202f1\u202f—\u202f*\u202fTeaching_Assign
- Enrollment\u202f1\u202f—\u202f1\u202fGrade
- Enrollment\u202f1\u202f—\u202f*\u202fAttendance"""


class AssignmentWorkspaceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        auth_rate_limiter.reset("register:testclient")
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)

        def override_get_db():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app, base_url="http://localhost:8000")
        response = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "Workspace Student",
                "email": "workspace@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
                "terms_accepted": True,
            },
        )
        self.assertEqual(response.status_code, 201)
        with Session(self.engine) as db:
            self.user = db.scalar(select(User).where(User.email == "workspace@example.com"))
            self.course = Course(
                user_id=self.user.id,
                google_course_id="course-workspace",
                course_name="Writing Studies",
            )
            db.add(self.course)
            db.flush()
            self.assignment = Assignment(
                user_id=self.user.id,
                course_id=self.course.id,
                google_assignment_id="assignment-workspace",
                title="Research Reflection",
                description="Discuss the supplied reading.",
                attachments=[],
                is_demo=False,
            )
            db.add(self.assignment)
            db.commit()
            self.user_id = self.user.id
            self.course_id = self.course.id
            self.assignment_id = self.assignment.id

    def _create_license(self, user_id: int, expires_at: datetime) -> None:
        now = datetime.now(UTC)
        with Session(self.engine) as db:
            if db.get(LicensingPolicy, 1) is None:
                db.add(
                    LicensingPolicy(
                        id=1,
                        launch_at=now - timedelta(days=30),
                        grandfathering_days=30,
                    )
                )
            plan = db.scalar(select(Plan).where(Plan.code == "semester"))
            if plan is None:
                plan = Plan(
                    code="semester",
                    name="Semester",
                    amount_paisa=50000,
                    duration_months=6,
                    is_enabled=True,
                )
                db.add(plan)
                db.flush()
            db.add(
                License(
                    user_id=user_id,
                    plan_id=plan.id,
                    starts_at=now - timedelta(days=30),
                    expires_at=expires_at,
                )
            )
            db.commit()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        auth_rate_limiter.reset("register:testclient")
        self.client.close()
        self.engine.dispose()

    def test_expired_student_keeps_read_only_access_to_cached_classroom_data(self) -> None:
        self._create_license(self.user_id, datetime.now(UTC) - timedelta(days=1))

        workspace = self.client.get(
            f"/api/assignments/{self.assignment_id}/workspace"
        )
        classroom = self.client.get("/api/classroom/assignments")

        self.assertEqual(workspace.status_code, 200)
        self.assertEqual(workspace.json()["license"], {"status": "expired", "active": False})
        self.assertEqual(classroom.status_code, 200)
        self.assertEqual(
            [item["id"] for item in classroom.json()["assignments"]],
            [self.assignment_id],
        )

    def test_expired_student_cannot_edit_create_restore_export_approve_or_submit(self) -> None:
        self._create_license(self.user_id, datetime.now(UTC) - timedelta(days=1))
        with Session(self.engine) as db:
            assignment = db.get(Assignment, self.assignment_id)
            assignment.draft_content = "Existing saved draft"
            version = AssignmentDraftVersion(
                assignment_id=self.assignment_id,
                version=1,
                content="Existing saved draft",
                source="student",
            )
            db.add(version)
            db.flush()
            saved_export = AssignmentExport(
                assignment_id=self.assignment_id,
                draft_version_id=version.id,
                file_format="pdf",
                file_content=b"existing export",
            )
            db.add(saved_export)
            second_assignment = Assignment(
                user_id=self.user_id,
                course_id=self.course_id,
                google_assignment_id="assignment-without-draft",
                title="Assignment without a draft",
                description="Instructions",
                attachments=[],
                is_demo=False,
            )
            db.add(second_assignment)
            db.commit()
            second_assignment_id = second_assignment.id
            saved_export_id = saved_export.id
            version_id = version.id

        edit = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": "Attempted replacement"},
        )
        create = self.client.put(
            f"/api/assignments/{second_assignment_id}/draft",
            json={"content": "Attempted new draft"},
        )
        suggestion = self.client.post(
            f"/api/assignments/{self.assignment_id}/suggestions",
            json={"action": "rewrite"},
        )
        restore = self.client.post(
            f"/api/assignments/{self.assignment_id}/versions/restore",
            json={"version_id": version_id},
        )
        generate_export = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/pdf"
        )
        download_export = self.client.get(
            f"/api/assignments/{self.assignment_id}/exports/{saved_export_id}"
        )
        approve = self.client.post(
            f"/api/assignments/{self.assignment_id}/approve"
        )
        with patch("app.api.routes.assignments.submit_approved_assignment") as submit:
            submission = self.client.post(
                f"/api/assignments/{self.assignment_id}/submit"
            )
            submit.assert_not_called()

        self.assertEqual(
            [
                edit.status_code,
                create.status_code,
                suggestion.status_code,
                restore.status_code,
                generate_export.status_code,
                download_export.status_code,
                approve.status_code,
                submission.status_code,
            ],
            [403] * 8,
        )
        with Session(self.engine) as db:
            assignment = db.get(Assignment, self.assignment_id)
            self.assertEqual(assignment.draft_content, "Existing saved draft")
            versions = db.scalars(
                select(AssignmentDraftVersion).where(
                    AssignmentDraftVersion.assignment_id == self.assignment_id
                )
            ).all()
            exports = db.scalars(
                select(AssignmentExport).where(
                    AssignmentExport.assignment_id == self.assignment_id
                )
            ).all()
            self.assertEqual(len(versions), 1)
            self.assertEqual(len(exports), 1)
            self.assertEqual(db.scalar(select(Approval.id)), None)
            self.assertIsNone(db.get(Assignment, second_assignment_id).draft_content)

    def test_license_status_and_assignment_access_are_isolated_per_student(self) -> None:
        self._create_license(self.user_id, datetime.now(UTC) - timedelta(days=1))
        now = datetime.now(UTC)
        with Session(self.engine) as db:
            other_user = User(
                full_name="Active Student",
                email="active@example.com",
            )
            db.add(other_user)
            db.flush()
            course = Course(
                user_id=other_user.id,
                google_course_id="active-course",
                course_name="Active Course",
            )
            db.add(course)
            db.flush()
            other_assignment = Assignment(
                user_id=other_user.id,
                course_id=course.id,
                google_assignment_id="active-assignment",
                title="Active Student Assignment",
                description="Instructions",
                attachments=[],
                is_demo=False,
            )
            db.add(other_assignment)
            db.flush()
            plan = db.scalar(select(Plan).where(Plan.code == "semester"))
            db.add(
                License(
                    user_id=other_user.id,
                    plan_id=plan.id,
                    starts_at=now - timedelta(days=1),
                    expires_at=now + timedelta(days=30),
                )
            )
            db.commit()
            other_user_id = other_user.id
            other_assignment_id = other_assignment.id

        current_user = {
            "user": User(
                id=self.user_id,
                full_name="Workspace Student",
                email="workspace@example.com",
            )
        }
        app.dependency_overrides[get_current_user] = lambda: current_user["user"]
        expired_response = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": "Expired user cannot save"},
        )
        current_user["user"] = User(
            id=other_user_id,
            full_name="Active Student",
            email="active@example.com",
        )
        active_response = self.client.put(
            f"/api/assignments/{other_assignment_id}/draft",
            json={"content": "Active user can save"},
        )

        self.assertEqual(expired_response.status_code, 403)
        self.assertEqual(active_response.status_code, 200)

    def test_saves_and_restores_versions_without_deleting_history(self) -> None:
        first = "Original draft"
        edited = "Student's saved edit"
        self.assertEqual(
            self.client.put(
                f"/api/assignments/{self.assignment_id}/draft",
                json={"content": first},
            ).status_code,
            200,
        )
        self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": edited},
        )

        history = self.client.get(
            f"/api/assignments/{self.assignment_id}/workspace"
        ).json()["versions"]
        self.assertEqual([version["version"] for version in history], [2, 1])
        self.assertEqual(history[0]["content"], edited)

        response = self.client.post(
            f"/api/assignments/{self.assignment_id}/versions/restore",
            json={"version_id": history[1]["id"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["draft_content"], first)
        self.assertEqual(response.json()["version"]["source"], "restored")
        restored_history = self.client.get(
            f"/api/assignments/{self.assignment_id}/workspace"
        ).json()["versions"]
        self.assertEqual(len(restored_history), 3)
        self.assertEqual(restored_history[1]["content"], edited)

    def test_ai_response_is_only_a_suggestion_until_student_saves_it(self) -> None:
        original = "My own starting paragraph."
        self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": original},
        )
        before = self.client.get(
            f"/api/assignments/{self.assignment_id}/workspace"
        ).json()
        with patch(
            "app.api.routes.assignments.create_assignment_suggestion",
            return_value="A proposed replacement.",
        ) as generate:
            response = self.client.post(
                f"/api/assignments/{self.assignment_id}/suggestions",
                json={"action": "rewrite", "instruction": "Improve clarity."},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["suggestion"], "A proposed replacement.")
        self.assertEqual(generate.call_args.kwargs["current_draft"], original)
        workspace = self.client.get(
            f"/api/assignments/{self.assignment_id}/workspace"
        ).json()
        self.assertEqual(workspace["assignment"]["draft_content"], original)
        self.assertEqual(workspace["versions"], before["versions"])

    def test_exports_use_the_latest_saved_version(self) -> None:
        original_content = "# Earlier heading\n\nEarlier saved student content."
        latest_content = "# Final heading\n\nLatest saved student content."
        self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": original_content},
        )
        self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": latest_content},
        )

        pdf = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/pdf"
        )
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.headers["content-type"], "application/pdf")
        self.assertEqual(pdf.headers["x-assignment-version"], "2")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        with pymupdf.open(stream=pdf.content, filetype="pdf") as pdf_document:
            pdf_text = "\n".join(page.get_text() for page in pdf_document)
        self.assertIn("Latest saved student content.", pdf_text)
        self.assertNotIn("Earlier saved student content.", pdf_text)

        docx = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/docx"
        )
        self.assertEqual(docx.status_code, 200)
        self.assertEqual(docx.headers["x-assignment-version"], "2")
        document = Document(BytesIO(docx.content))
        paragraphs = [paragraph.text for paragraph in document.paragraphs]
        self.assertIn("Latest saved student content.", paragraphs)
        self.assertNotIn("Earlier saved student content.", paragraphs)
        self.assertIn("Final heading", paragraphs)
        exports = self.client.get(
            f"/api/assignments/{self.assignment_id}/workspace"
        ).json()["exports"]
        self.assertEqual(
            [(entry["format"], entry["version"]) for entry in exports],
            [("docx", 2), ("pdf", 2)],
        )

    def test_project_schedule_csv_export_contains_importable_tasks_and_milestones(self) -> None:
        schedule = """# Semester Project — Student Portal
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

Remaining Microsoft Project actions: import the CSV, confirm the project calendar,
review the Gantt Chart, and save the actual .mpp file. ClassMate AI generated the
schedule CSV; it did not create an .mpp file or operate Microsoft Project.
"""
        saved = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": schedule},
        )
        self.assertEqual(saved.status_code, 200)

        response = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/csv"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        self.assertIn(".csv", response.headers["content-disposition"])
        records = list(
            csv.DictReader(StringIO(response.content.decode("utf-8-sig")))
        )
        self.assertEqual(
            list(records[0]),
            ["ID", "Task Name", "Duration", "Start", "Finish", "Predecessors", "Milestone"],
        )
        self.assertEqual(len([row for row in records if row["Milestone"] == "No"]), 10)
        self.assertEqual(len([row for row in records if row["Milestone"] == "Yes"]), 3)
        self.assertEqual(records[0]["Start"], "2026-11-09")
        self.assertEqual(records[8]["Predecessors"], "7, 8")
        self.assertEqual(records[-1]["Duration"], "0d")
        self.assertEqual(records[-1]["Milestone"], "Yes")

        export_id = response.headers["x-assignment-export"]
        saved_export = self.client.get(
            f"/api/assignments/{self.assignment_id}/exports/{export_id}"
        )
        self.assertEqual(saved_export.status_code, 200)
        self.assertEqual(saved_export.content, response.content)
        workspace_exports = self.client.get(
            f"/api/assignments/{self.assignment_id}/workspace"
        ).json()["exports"]
        self.assertEqual(workspace_exports[0]["format"], "csv")

    def test_csv_export_rejects_drafts_without_importable_project_schedule(self) -> None:
        self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": "# Introduction\nThis is not a project schedule."},
        )
        response = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/csv"
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("at least 8 scheduled tasks", response.json()["detail"])

    def test_exports_render_report_tables_lists_and_code(self) -> None:
        report = """# Introduction
This report includes a proposed semester project plan.

## Lab Task 1 (installation)
The student must run this deployment configuration locally.

```xml
<Configuration>
  <Add OfficeClientEdition="64" />
</Configuration>
```

## Lab Task 1 (semester schedule)
| Task | Duration | Dependency |
|---|---|---|
| Requirements and scope | 5 days | None |
| Design review milestone | 1 day | Requirements and scope |

## Lab Task 2 (Trello board)
- Create a semester project list.
- Add a requirements checklist.
3. Capture real screenshots locally.
"""
        saved = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": report},
        )
        self.assertEqual(saved.status_code, 200)

        pdf = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/pdf"
        )
        self.assertEqual(pdf.status_code, 200)
        with pymupdf.open(stream=pdf.content, filetype="pdf") as pdf_document:
            pdf_text = "\n".join(page.get_text() for page in pdf_document)
        for expected in (
            "Lab Task 1 (installation)",
            "Lab Task 1 (semester schedule)",
            "Requirements and scope",
            "Design review milestone",
            "Create a semester project list.",
            "<Configuration>",
            "3. Capture real screenshots locally.",
        ):
            self.assertIn(expected, pdf_text)

        docx = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/docx"
        )
        self.assertEqual(docx.status_code, 200)
        document = Document(BytesIO(docx.content))
        paragraph_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        table_text = "\n".join(
            cell.text for table in document.tables for row in table.rows for cell in row.cells
        )
        combined_text = f"{paragraph_text}\n{table_text}"
        for expected in (
            "Lab Task 1 (installation)",
            "Lab Task 1 (semester schedule)",
            "Requirements and scope",
            "Design review milestone",
            "Create a semester project list.",
            "<Configuration>",
            "3. Capture real screenshots locally.",
        ):
            self.assertIn(expected, combined_text)
        self.assertEqual(len(document.tables), 1)

    def test_mandatory_student_management_figures_are_embedded_in_pdf_and_docx(self) -> None:
        with Session(self.engine) as db:
            assignment = db.get(Assignment, self.assignment_id)
            assignment.description = _SMS_FIGURE_INSTRUCTIONS
            db.commit()

        figure_draft = _SMS_FIGURE_DRAFT.replace(
            _SMS_FIGURE_RELATIONSHIP_BLOCK,
            _SAVED_SMS_RELATIONSHIPS,
        )
        prepared, figures = prepare_assignment_figures(
            figure_draft,
            _SMS_FIGURE_INSTRUCTIONS,
        )
        self.assertEqual(list(figures), [1, 2, 3, 4, 5])
        self.assertEqual(prepared.count("[[GENERATED_FIGURE:"), 5)
        self.assertEqual(
            [
                int(number)
                for number in re.findall(r"\[\[GENERATED_FIGURE:(\d+)\]\]", prepared)
            ],
            [1, 2, 3, 4, 5],
        )
        self.assertNotIn("Student Action Required", prepared)
        self.assertNotIn("screenshot not captured", prepared)
        self.assertNotIn("Placeholder", prepared)
        self.assertNotIn("By inserting the indicated figures", prepared)
        self.assertIn("The generated figures are embedded in this document.", prepared)
        self.assertNotIn(
            "Insert a mock-up of a test-case management screen",
            prepared,
        )
        self.assertNotIn("Proposed illustration", prepared)
        self.assertNotIn("Create a testing mock-up", prepared)
        self.assertIn(
            "not genuine screenshots or evidence of external software activity",
            prepared,
        )
        for number, figure in figures.items():
            self.assertEqual(figure.number, number)
            self.assertTrue(figure.image.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertIn(f"{number}. Figure {number}:", prepared)
        reusable_pack = render_figure_pack(
            [FigureDefinition(1, "Reusable diagram", lambda: figures[1].image)]
        )
        self.assertEqual(reusable_pack[1].caption, "Reusable diagram")
        future_pack = AssignmentFigurePack(
            matches=lambda _content, _instructions, _title: True,
            build=lambda source, _instructions: (
                source
                + "\n[[GENERATED_FIGURE:1]]\n"
                + "Student Action Required - Figure 1: Insert a workflow illustration.\n"
                + "*Placeholder - insert an illustration showing the requested design.*",
                [
                    FigureDefinition(
                        1,
                        "Future assignment illustration",
                        lambda: figures[1].image,
                    )
                ],
            ),
        )
        with patch("app.services.assignment_figures._ASSIGNMENT_FIGURE_PACKS", []):
            register_assignment_figure_pack(future_pack)
            future_content, future_figures = prepare_assignment_figures(
                "A different assignment",
                None,
            )
        self.assertIn("[[GENERATED_FIGURE:1]]", future_content)
        self.assertNotIn("Placeholder", future_content)
        self.assertNotIn("Student Action Required", future_content)
        self.assertEqual(future_figures[1].caption, "Future assignment illustration")
        reusable_erd_pack = AssignmentFigurePack(
            matches=lambda _content, _instructions, _title: True,
            build=lambda source, _instructions: (
                source + "\n[[GENERATED_FIGURE:1]]",
                [
                    FigureDefinition(
                        1,
                        "Entity-Relationship Diagram",
                        lambda: figures[3].image,
                    )
                ],
            ),
        )
        generic_placeholder = (
            "*Placeholder - insert an ERD that includes entities and relationships: ?*"
        )
        with patch("app.services.assignment_figures._ASSIGNMENT_FIGURE_PACKS", []):
            register_assignment_figure_pack(reusable_erd_pack)
            resolved_erd, _ = prepare_assignment_figures(
                f"Database design\n{generic_placeholder}",
                None,
            )
        self.assertNotIn(generic_placeholder, resolved_erd)
        with_additional_figure = (
            figure_draft
            + "\n### Student Action Required Summary\n"
            + "| Figure | Required Action |\n|---|---|\n"
            + "| Figure 6 | Capture the student's real software screenshot |\n"
        )
        prepared_with_additional_figure, _ = prepare_assignment_figures(
            with_additional_figure,
            _SMS_FIGURE_INSTRUCTIONS,
        )
        self.assertIn("Figure 6", prepared_with_additional_figure)
        self.assertIn("Capture the student's real software screenshot", prepared_with_additional_figure)

        screenshot_required_instructions = (
            _SMS_FIGURE_INSTRUCTIONS
            + "\nCapture a genuine software screenshot in Figure 5."
        )
        screenshot_content, _ = prepare_assignment_figures(
            figure_draft,
            screenshot_required_instructions,
        )
        self.assertEqual(
            screenshot_content.count("Student Action Required - Figure"),
            1,
        )
        self.assertIn("Student Action Required - Figure 5", screenshot_content)
        self.assertNotIn("Figure 1 (screenshot not captured)", screenshot_content)
        self.assertNotIn("*Placeholder", screenshot_content)

        saved = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": figure_draft},
        )
        self.assertEqual(saved.status_code, 200)

        pdf = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/pdf"
        )
        self.assertEqual(pdf.status_code, 200)
        with pymupdf.open(stream=pdf.content, filetype="pdf") as pdf_document:
            pdf_text = "\n".join(page.get_text() for page in pdf_document)
            image_count = sum(len(page.get_images(full=True)) for page in pdf_document)
            entity_table_pages = {
                page_number
                for page_number, page in enumerate(pdf_document)
                if any(
                    key in page.get_text()
                    for key in (
                        "student_id",
                        "course_id",
                        "enrollment_id",
                        "teacher_id",
                        "assign_id",
                        "grade_id",
                        "attendance_id",
                    )
                )
            }
        self.assertEqual(image_count, 5)
        self.assertEqual(
            len(entity_table_pages),
            1,
            "The compact entity table should stay together on one PDF page.",
        )
        self.assertNotIn("Placeholder - insert an ERD", pdf_text)
        self.assertNotIn("By inserting the indicated figures", pdf_text)
        normalized_pdf_text = " ".join(pdf_text.split())
        for expected in (
            "Figure 1: Student Management System",
            "Figure 2: UML Use Case Diagram",
            "Figure 3: Entity-Relationship Diagram",
            "Figure 4: Three-Tier System Architecture",
            "Figure 5: Illustrative Testing Interface Mockup",
            "Actual Result",
            "Pass/Fail",
            "Not run",
            "List of Figures",
        ):
            self.assertIn(expected, normalized_pdf_text)
        self.assertIn(
            "Generated illustrations and mockups are not genuine screenshots or evidence",
            normalized_pdf_text,
        )
        self.assertNotIn(
            "Insert a mock-up of a test-case management screen",
            normalized_pdf_text,
        )
        self.assertNotIn("Proposed illustration", normalized_pdf_text)
        self.assertNotIn("Create a testing mock-up", normalized_pdf_text)
        self.assertLess(
            normalized_pdf_text.rindex("6. List of Figures"),
            normalized_pdf_text.index("7. Conclusion"),
        )
        self.assertNotIn("Student Action Required", pdf_text)
        self.assertNotIn("screenshot not captured", pdf_text)
        self.assertNotIn("Figure 1 (screenshot", pdf_text)

        docx = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/docx"
        )
        self.assertEqual(docx.status_code, 200)
        document = Document(BytesIO(docx.content))
        self.assertEqual(len(document.inline_shapes), 5)
        entity_tables = [
            table
            for table in document.tables
            if table.rows and table.rows[0].cells[0].text == "Entity"
        ]
        self.assertEqual(len(entity_tables), 1)
        self.assertEqual(len(entity_tables[0].rows), 8)
        with ZipFile(BytesIO(docx.content)) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("w:tblHeader", document_xml)
        self.assertIn("w:cantSplit", document_xml)
        paragraphs = document.paragraphs
        image_paragraph_indexes = [
            index
            for index, paragraph in enumerate(paragraphs)
            if paragraph._p.xpath(".//w:drawing")
        ]
        self.assertEqual(len(image_paragraph_indexes), 5)
        for number, index in enumerate(image_paragraph_indexes, start=1):
            self.assertIn(f"Figure {number}:", paragraphs[index + 1].text)
        docx_text = "\n".join(paragraph.text for paragraph in paragraphs)
        self.assertIn("This illustrative mockup displays Test ID", docx_text)
        self.assertNotIn(
            "Insert a mock-up of a test-case management screen",
            docx_text,
        )
        self.assertNotIn("Proposed illustration", docx_text)
        self.assertNotIn("Create a testing mock-up", docx_text)
        self.assertIn(
            "not genuine screenshots or evidence of external software activity",
            docx_text,
        )
        self.assertIn("not a screenshot of a real application", docx_text)
        self.assertIn("Not run", docx_text)
        self.assertNotIn("Placeholder - insert an ERD", docx_text)
        self.assertNotIn("By inserting the indicated figures", docx_text)
        self.assertLess(
            docx_text.rindex("6. List of Figures"),
            docx_text.index("7. Conclusion"),
        )
        self.assertNotIn("Student Action Required", docx_text)
        self.assertNotIn("screenshot not captured", docx_text)
        with ZipFile(BytesIO(docx.content)) as archive:
            media_files = [
                name for name in archive.namelist() if name.startswith("word/media/")
            ]
        self.assertEqual(len(media_files), 5)

    def test_erd_relationship_parser_accepts_numbered_variations_and_tables(self) -> None:
        relationship_formats = (
            """*Relationships (crow’s‑foot notation):*
- Student\u202f1\u202f—\u202f*\u202fEnrollment
- Course 1:* Enrollment
- Teacher (1) → Teaching_Assign (many)
- Course (one) -> Teaching_Assign (many)
- Enrollment 1:1 Grade
- Enrollment (1) -> Attendance (many)""",
            """## Relationships
1. **Student** (1) → **Enrollment** (many)
2. Course 1:* Enrollment
3. Teacher (1) -> Teaching_Assign (many)
4. Course one-to-many Teaching_Assign
5. Enrollment (one) -> Grade (one)
6. Enrollment 1—many Attendance""",
            """## ERD Relationships
| Parent | Parent Cardinality | Child | Child Cardinality |
|---|---|---|---|
| Student | 1 | Enrollment | many |
| Course | 1 | Enrollment | many |
| Teacher | one | Teaching_Assign | many |
| Course | 1 | Teaching_Assign | * |
| Enrollment | 1 | Grade | 1 |
| Enrollment | 1 | Attendance | many |""",
        )
        expected_pairs = [
            ("Student", "Enrollment", "1", "*"),
            ("Course", "Enrollment", "1", "*"),
            ("Teacher", "Teaching_Assign", "1", "*"),
            ("Course", "Teaching_Assign", "1", "*"),
            ("Enrollment", "Grade", "1", "1"),
            ("Enrollment", "Attendance", "1", "*"),
        ]
        for relationship_text in relationship_formats:
            with self.subTest(relationship_text=relationship_text[:50]):
                draft = _SMS_FIGURE_DRAFT.replace(
                    _SMS_FIGURE_RELATIONSHIP_BLOCK,
                    relationship_text,
                )
                entities, relationships = _parse_entities(draft)
                self.assertEqual(len(entities), 7)
                self.assertEqual(
                    [
                        (
                            item.parent,
                            item.child,
                            item.parent_cardinality,
                            item.cardinality,
                        )
                        for item in relationships
                    ],
                    expected_pairs,
                )

    def test_erd_relationship_parser_rejects_missing_ambiguous_and_unknown_rows(self) -> None:
        malformed_relationships = (
            (
                "*Relationships:* \n- Student many Enrollment",
                "unsupported or ambiguous",
            ),
            (
                "*Relationships:* \n- Student 1-* Department",
                "could not resolve both endpoints",
            ),
            (
                "*Relationships:* \n- Student 1-* Enrollment",
                "six valid relationships",
            ),
        )
        for relationship_text, diagnostic in malformed_relationships:
            with self.subTest(relationship_text=relationship_text):
                draft = _SMS_FIGURE_DRAFT.replace(
                    _SMS_FIGURE_RELATIONSHIP_BLOCK,
                    relationship_text,
                )
                with self.assertRaises(AssignmentFigureGenerationError) as raised:
                    _parse_entities(draft)
                self.assertIn(diagnostic, str(raised.exception))

    def test_saved_sms_relationships_render_into_erd_with_all_entities_and_edges(self) -> None:
        draft = _SMS_FIGURE_DRAFT.replace(
            _SMS_FIGURE_RELATIONSHIP_BLOCK,
            _SAVED_SMS_RELATIONSHIPS,
        )
        entities, relationships = _parse_entities(draft)
        expected_entities = {
            "student",
            "course",
            "enrollment",
            "teacher",
            "teaching_assign",
            "grade",
            "attendance",
        }
        self.assertEqual({entity.name.casefold() for entity in entities}, expected_entities)
        self.assertEqual(
            {
                (relationship.parent.casefold(), relationship.child.casefold())
                for relationship in relationships
            },
            {
                ("student", "enrollment"),
                ("course", "enrollment"),
                ("teacher", "teaching_assign"),
                ("course", "teaching_assign"),
                ("enrollment", "grade"),
                ("enrollment", "attendance"),
            },
        )
        erd_image = _figure_3(entities, relationships)
        with Image.open(BytesIO(erd_image)) as generated:
            self.assertEqual(generated.size, (1800, 1350))

    def test_mandatory_figure_generation_failure_rejects_exports_safely(self) -> None:
        with Session(self.engine) as db:
            assignment = db.get(Assignment, self.assignment_id)
            assignment.description = _SMS_FIGURE_INSTRUCTIONS
            db.commit()
        incomplete_draft = (
            "# Student Management System\n\n"
            "*Placeholder - insert an ERD with the required entities and relationships: ?*"
        )
        self.assertEqual(
            self.client.put(
                f"/api/assignments/{self.assignment_id}/draft",
                json={"content": incomplete_draft},
            ).status_code,
            200,
        )

        for file_format in ("pdf", "docx"):
            response = self.client.get(
                f"/api/assignments/{self.assignment_id}/documents/{file_format}"
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn("Mandatory assignment figures could not be generated", response.json()["detail"])

        workspace = self.client.get(
            f"/api/assignments/{self.assignment_id}/workspace"
        ).json()
        self.assertIn(
            "Placeholder - insert an ERD",
            workspace["assignment"]["draft_content"],
        )
        with Session(self.engine) as db:
            exports = db.scalars(
                select(AssignmentExport).where(
                    AssignmentExport.assignment_id == self.assignment_id,
                )
            ).all()
        self.assertEqual(exports, [])

    def test_broken_checklist_markup_renders_as_structured_tables(self) -> None:
        excerpt = """## Lab Task 2 — Trello board
Figures 7■8 show the required board setup.
| Board area | Checklist |
|---|---|
| Workspace | &#x20;☐ Create the workspace<br>&#x20;☑ Create the semester board |
  - [ ] Add the To Do, In Progress, and Done lists
  - [ ] Add labels and due dates
| Card | Checklist |
|---|---|
| Project plan | &#x20;☐ Add task cards<br>&#x20;☐ Add task checklists |
"""
        parsed = _plain_lines(excerpt)
        tables = [block for block in parsed if block[0] == "table"]
        self.assertEqual(len(tables), 2)
        first_rows = tables[0][1]
        second_rows = tables[1][1]
        self.assertEqual(len(first_rows), 2)
        self.assertEqual(len(first_rows[0]), 2)
        self.assertIn("[ ] Create the workspace", first_rows[1][1])
        self.assertIn("[x] Create the semester board", first_rows[1][1])
        self.assertIn("[ ] Add the To Do, In Progress, and Done lists", first_rows[1][1])
        self.assertIn("[ ] Add labels and due dates", first_rows[1][1])
        self.assertIn("[ ] Add task checklists", second_rows[1][1])
        combined_text = "\n".join(
            text if isinstance(text, str) else "\n".join(
                "\n".join(row) for row in text
            )
            for _, text in parsed
        )
        self.assertIn("Figures 7-8", combined_text)
        self.assertNotIn("&#x20;", combined_text)
        self.assertNotIn("☐", combined_text)
        self.assertNotIn("☑", combined_text)
        self.assertNotIn("■", combined_text)

        saved = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": excerpt},
        )
        self.assertEqual(saved.status_code, 200)
        pdf = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/pdf"
        )
        self.assertEqual(pdf.status_code, 200)
        with pymupdf.open(stream=pdf.content, filetype="pdf") as pdf_document:
            pdf_text = "\n".join(page.get_text() for page in pdf_document)
        self.assertIn("Figures 7-8", pdf_text)
        self.assertIn("Create the workspace", pdf_text)
        self.assertIn("Add the To Do, In Progress, and Done lists", pdf_text)
        self.assertNotIn("&#x20;", pdf_text)
        self.assertNotIn("■", pdf_text)

        docx = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/docx"
        )
        self.assertEqual(docx.status_code, 200)
        document = Document(BytesIO(docx.content))
        self.assertEqual(len(document.tables), 2)
        self.assertEqual(len(document.tables[0].rows), 2)
        table_text = "\n".join(
            cell.text
            for table in document.tables
            for row in table.rows
            for cell in row.cells
        )
        self.assertIn("[ ] Create the workspace", table_text)
        self.assertIn("[x] Create the semester board", table_text)
        self.assertIn("[ ] Add the To Do, In Progress, and Done lists", table_text)
        self.assertIn("[ ] Add labels and due dates", table_text)
        docx_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn("Figures 7-8", docx_text)
        self.assertNotIn("&#x20;", f"{docx_text}\n{table_text}")

    def test_markdown_formatting_links_and_cover_render_in_pdf_and_docx(self) -> None:
        content = """## 1. Introduction
**Assignment Title:** A practical report with *emphasis*.

---

[Introduction](#introduction) is the contents link.

### Deliverables
1. **First item** with *italic text*.
2. Second item with a [reference](https://example.com).
- A bullet with **bold text**.

Malformed **emphasis remains visible and complete.

\\## Escaped Heading
\\*\\*Escaped bold\\*\\* and \\*escaped italic\\*.
\\| Name \\| Value \\|
\\|---\\|---\\|
\\| one \\| two \\|
Intentional unmatched \\* wildcard.
`code \\*\\* stays literal`
"""
        with Session(self.engine) as db:
            assignment = db.get(Assignment, self.assignment_id)
            assignment.title = "*A(*"
            user = db.scalar(select(User).where(User.email == "workspace@example.com"))
            user.roll_number = "ST-204"
            db.commit()
        saved = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": content},
        )
        self.assertEqual(saved.status_code, 200)

        pdf = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/pdf"
        )
        self.assertEqual(pdf.status_code, 200)
        with pymupdf.open(stream=pdf.content, filetype="pdf") as pdf_document:
            pdf_text = "\n".join(page.get_text() for page in pdf_document)
            pdf_links = [
                link
                for page in pdf_document
                for link in page.get_links()
            ]
        self.assertIn("Assignment Title", pdf_text)
        self.assertNotIn("A(", pdf_text)
        self.assertNotIn("*A(*", pdf_text)
        self.assertIn("Student Name", pdf_text)
        self.assertIn("Student ID", pdf_text)
        self.assertIn("ST-204", pdf_text)
        self.assertIn("Course", pdf_text)
        self.assertIn("Writing Studies", pdf_text)
        self.assertIn("Date", pdf_text)
        self.assertNotIn("Instructor:", pdf_text)
        self.assertNotIn("**Assignment Title:**", pdf_text)
        self.assertNotIn("[Introduction](#introduction)", pdf_text)
        self.assertNotIn("---", pdf_text)
        self.assertIn("Assignment Title:", pdf_text)
        self.assertIn("emphasis", pdf_text)
        self.assertIn("First item", pdf_text)
        self.assertIn("Second item", pdf_text)
        self.assertIn("Malformed **emphasis remains visible and complete.", pdf_text)
        self.assertIn("Escaped Heading", pdf_text)
        self.assertIn("Escaped bold", pdf_text)
        self.assertIn("escaped italic", pdf_text.casefold())
        self.assertIn("Name", pdf_text)
        self.assertIn("Value", pdf_text)
        self.assertIn("one", pdf_text)
        self.assertIn("two", pdf_text)
        self.assertIn(r"\* wildcard", pdf_text)
        self.assertIn(r"code \*\* stays literal", pdf_text)
        self.assertNotIn(r"\##", pdf_text)
        self.assertNotIn(r"\|", pdf_text)
        self.assertTrue(
            any(link.get("kind") == pymupdf.LINK_GOTO for link in pdf_links),
            "The PDF heading link should navigate to the Introduction heading.",
        )

        docx = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/docx"
        )
        self.assertEqual(docx.status_code, 200)
        document = Document(BytesIO(docx.content))
        paragraph_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn("Assignment Title", paragraph_text)
        self.assertNotIn("A(", paragraph_text)
        self.assertNotIn("*A(*", paragraph_text)
        self.assertIn("Student Name:", paragraph_text)
        self.assertIn("Student ID: ST-204", paragraph_text)
        self.assertIn("Course: Writing Studies", paragraph_text)
        self.assertIn("Date:", paragraph_text)
        self.assertNotIn("Instructor:", paragraph_text)
        self.assertNotIn("**Assignment Title:**", paragraph_text)
        self.assertNotIn("[Introduction](#introduction)", paragraph_text)
        self.assertNotIn("---", paragraph_text)
        self.assertIn("Malformed **emphasis remains visible and complete.", paragraph_text)
        self.assertIn("Escaped Heading", paragraph_text)
        self.assertIn(r"\* wildcard", paragraph_text)
        self.assertIn(r"code \*\* stays literal", paragraph_text)
        table_text = "\n".join(
            cell.text
            for table in document.tables
            for row in table.rows
            for cell in row.cells
        )
        self.assertIn("Name", table_text)
        self.assertIn("Value", table_text)
        self.assertIn("one", table_text)
        self.assertIn("two", table_text)
        self.assertTrue(
            any(run.bold for paragraph in document.paragraphs for run in paragraph.runs),
            "Bold Markdown should produce a bold Word run.",
        )
        self.assertTrue(
            any(run.italic for paragraph in document.paragraphs for run in paragraph.runs),
            "Italic Markdown should produce an italic Word run.",
        )
        with ZipFile(BytesIO(docx.content)) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
            relationships_xml = archive.read("word/_rels/document.xml.rels").decode("utf-8")
        self.assertIn('w:anchor="introduction"', document_xml)
        self.assertIn('w:name="introduction"', document_xml)
        self.assertIn("https://example.com", relationships_xml)

    def test_cover_title_uses_valid_title_or_neutral_placeholder(self) -> None:
        content = (
            "**Assignment Title:** *A(*\n\n"
            "**Course:** AI\n\n"
            "# Report\n\nThe conclusion is complete."
        )

        def exported_title(title: str | None) -> tuple[str, str]:
            with Session(self.engine) as db:
                assignment = db.get(Assignment, self.assignment_id)
                assignment.title = title
                db.commit()
            pdf_response = self.client.put(
                f"/api/assignments/{self.assignment_id}/draft",
                json={"content": content},
            )
            self.assertEqual(pdf_response.status_code, 200)
            pdf_response = self.client.get(
                f"/api/assignments/{self.assignment_id}/documents/pdf"
            )
            self.assertEqual(pdf_response.status_code, 200)
            with pymupdf.open(
                stream=pdf_response.content,
                filetype="pdf",
            ) as pdf_document:
                pdf_text = "\n".join(page.get_text() for page in pdf_document)

            docx_response = self.client.get(
                f"/api/assignments/{self.assignment_id}/documents/docx"
            )
            self.assertEqual(docx_response.status_code, 200)
            document = Document(BytesIO(docx_response.content))
            return pdf_text, "\n".join(
                paragraph.text for paragraph in document.paragraphs
            )

        valid_pdf, valid_docx = exported_title("Semester Project")
        self.assertIn("Semester Project", valid_pdf)
        self.assertIn("Semester Project", valid_docx)
        self.assertIn("Course: AI", valid_pdf)
        self.assertIn("Course: AI", valid_docx)
        self.assertNotIn("A(", valid_pdf)
        self.assertNotIn("A(", valid_docx)
        self.assertEqual(_display_assignment_title(None), "Assignment Title")
        for invalid_title in ("A(", "*A(*", "", "  "):
            with self.subTest(invalid_title=invalid_title):
                pdf_text, docx_text = exported_title(invalid_title)
                self.assertIn("Assignment Title", pdf_text)
                self.assertIn("Assignment Title", docx_text)
                self.assertNotIn("A(", pdf_text)
                self.assertNotIn("A(", docx_text)

    def test_exported_conclusion_is_complete_and_preserves_final_content(self) -> None:
        content = """## Conclusion
The report includes the required design and analysis.

- A complete database schema.
- A documented testing approach.

The conclusion ends with this complete final statement.
"""
        self.assertEqual(
            self.client.put(
                f"/api/assignments/{self.assignment_id}/draft",
                json={"content": content},
            ).status_code,
            200,
        )
        pdf = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/pdf"
        )
        self.assertEqual(pdf.status_code, 200)
        with pymupdf.open(stream=pdf.content, filetype="pdf") as pdf_document:
            page_text = [page.get_text() for page in pdf_document]
        self.assertIn("A complete database schema.", "\n".join(page_text))
        self.assertIn("A documented testing approach.", "\n".join(page_text))
        self.assertIn(
            "The conclusion ends with this complete final statement.",
            page_text[-1],
        )

        docx = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/docx"
        )
        self.assertEqual(docx.status_code, 200)
        document = Document(BytesIO(docx.content))
        content_paragraphs = [
            paragraph.text for paragraph in document.paragraphs if paragraph.text
        ]
        self.assertEqual(
            content_paragraphs[-1],
            "The conclusion ends with this complete final statement.",
        )

    def test_screenshot_figure_placeholders_are_not_exported_as_evidence(self) -> None:
        with Session(self.engine) as db:
            assignment = db.get(Assignment, self.assignment_id)
            assignment.description = (
                "Create a Trello board and include a screenshot in Figure 7."
            )
            db.commit()
        content = (
            "# Lab Task 2\n\n"
            "Figure 7: Trello workspace overview showing the newly created workspace "
            "and board."
        )
        saved = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": content},
        )
        self.assertEqual(saved.status_code, 200)

        pdf = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/pdf"
        )
        self.assertEqual(pdf.status_code, 200)
        with pymupdf.open(stream=pdf.content, filetype="pdf") as pdf_document:
            pdf_text = "\n".join(page.get_text() for page in pdf_document)
            self.assertTrue(all(not page.get_images() for page in pdf_document))
        self.assertIn("Student Action Required", pdf_text)
        self.assertIn("Figure 7 (screenshot not captured)", pdf_text)
        self.assertIn("Capture a genuine screenshot", pdf_text)
        self.assertIn("This placeholder is not evidence.", " ".join(pdf_text.split()))

        docx = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/docx"
        )
        self.assertEqual(docx.status_code, 200)
        document = Document(BytesIO(docx.content))
        docx_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn("Student Action Required", docx_text)
        self.assertIn("Figure 7 (screenshot not captured)", docx_text)
        self.assertIn("Capture a genuine screenshot", docx_text)
        self.assertIn("This placeholder is not evidence.", docx_text)
        with ZipFile(BytesIO(docx.content)) as archive:
            self.assertFalse(any(name.startswith("word/media/") for name in archive.namelist()))

    def test_teacher_figure_six_is_preserved_in_pdf_and_docx(self) -> None:
        with Session(self.engine) as db:
            assignment = db.get(Assignment, self.assignment_id)
            assignment.description = (
                "Include a screenshot as Figure 6 showing the task list and Gantt Chart."
            )
            db.commit()
        content = (
            "Student Action Required — Screenshot (not captured): "
            "Figure 1 – Placeholder for the screenshot of the task list and Gantt Chart."
        )
        saved = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": content},
        )
        self.assertEqual(saved.status_code, 200)

        pdf = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/pdf"
        )
        self.assertEqual(pdf.status_code, 200)
        with pymupdf.open(stream=pdf.content, filetype="pdf") as pdf_document:
            pdf_text = "\n".join(page.get_text() for page in pdf_document)
        self.assertIn("Student Action Required", pdf_text)
        self.assertIn("Figure 6 (screenshot not captured)", pdf_text)
        self.assertIn("task list and Gantt Chart", " ".join(pdf_text.split()))
        self.assertIn("This placeholder is not evidence.", " ".join(pdf_text.split()))
        self.assertNotIn("Figure 1", pdf_text)

        docx = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/docx"
        )
        self.assertEqual(docx.status_code, 200)
        document = Document(BytesIO(docx.content))
        docx_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn("Student Action Required", docx_text)
        self.assertIn("Figure 6 (screenshot not captured)", docx_text)
        self.assertIn("task list and Gantt Chart", docx_text)
        self.assertIn("This placeholder is not evidence.", docx_text)
        self.assertNotIn("Figure 1", docx_text)

    def test_figure_placeholders_are_unchanged_when_no_pack_matches(self) -> None:
        content = (
            "## Design\n"
            "*Placeholder - insert a diagram of the proposed workflow.*"
        )
        prepared, figures = prepare_assignment_figures(
            content,
            None,
            packs=[],
        )
        self.assertEqual(prepared, content)
        self.assertEqual(figures, {})

    def test_genuine_screenshot_requirement_is_distinguished_from_mockup(self) -> None:
        self.assertFalse(
            requires_genuine_screenshot(
                "Include a screenshot or illustrative mockup in Figure 5.",
                5,
            )
        )
        self.assertFalse(
            requires_genuine_screenshot(
                "Do not fabricate screenshots. A generated mockup is acceptable.",
                5,
            )
        )
        self.assertTrue(
            requires_genuine_screenshot(
                "Capture a genuine application screenshot in Figure 5.",
                5,
            )
        )
        self.assertFalse(
            requires_genuine_screenshot(
                "Capture a genuine application screenshot in Figure 5.",
                4,
            )
        )

    def test_adjacent_fragments_of_the_same_markdown_table_are_merged(self) -> None:
        content = """## Database Design
| Entity | Primary Key | Attributes |
|---|---|---|
| Student | student_id | first_name |
| Course | course_id | course_name |

| Entity | Primary Key | Attributes |
|---|---|---|
| Enrollment | enrollment_id | student_id (FK), course_id (FK) |
| Teacher | teacher_id | email |
"""
        parsed = _plain_lines(content)
        tables = [value for kind, value in parsed if kind == "table"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(
            [row[0].strip("*") for row in tables[0][1:]],
            ["Student", "Course", "Enrollment", "Teacher"],
        )
        self.assertIn("student_id (FK), course_id (FK)", tables[0][3][2])

        saved = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": content},
        )
        self.assertEqual(saved.status_code, 200)
        docx = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/docx"
        )
        self.assertEqual(docx.status_code, 200)
        document = Document(BytesIO(docx.content))
        entity_tables = [
            table
            for table in document.tables
            if table.rows and table.rows[0].cells[0].text == "Entity"
        ]
        self.assertEqual(len(entity_tables), 1)
        self.assertEqual(len(entity_tables[0].rows), 5)

        pdf = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/pdf"
        )
        self.assertEqual(pdf.status_code, 200)
        with pymupdf.open(stream=pdf.content, filetype="pdf") as pdf_document:
            pdf_text = "\n".join(page.get_text() for page in pdf_document)
        for entity in ("Student", "Course", "Enrollment", "Teacher"):
            self.assertIn(entity, pdf_text)

    def test_different_adjacent_markdown_tables_are_not_merged(self) -> None:
        content = """| Entity | Primary Key |
|---|---|
| Student | student_id |

| Relationship | Cardinality |
|---|---|
| Student to Enrollment | one-to-many |
"""
        tables = [value for kind, value in _plain_lines(content) if kind == "table"]
        self.assertEqual(len(tables), 2)

    def test_bullet_glyphs_remain_separate_exported_list_items(self) -> None:
        content = """## Conclusion
The report includes:

• A three-tier architecture.
• A testing interface mockup.
"""
        parsed = _plain_lines(content)
        bullet_items = [value for kind, value in parsed if kind == "bullet"]
        self.assertEqual(
            bullet_items,
            ["A three-tier architecture.", "A testing interface mockup."],
        )

        saved = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": content},
        )
        self.assertEqual(saved.status_code, 200)
        docx = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/docx"
        )
        self.assertEqual(docx.status_code, 200)
        document = Document(BytesIO(docx.content))
        conclusion_bullets = [
            paragraph.text
            for paragraph in document.paragraphs
            if paragraph.style.name == "List Bullet"
        ]
        self.assertEqual(
            conclusion_bullets,
            ["A three-tier architecture.", "A testing interface mockup."],
        )
        pdf = self.client.get(
            f"/api/assignments/{self.assignment_id}/documents/pdf"
        )
        self.assertEqual(pdf.status_code, 200)
        with pymupdf.open(stream=pdf.content, filetype="pdf") as pdf_document:
            pdf_text = "\n".join(page.get_text() for page in pdf_document)
        self.assertIn("A three-tier architecture.", pdf_text)
        self.assertIn("A testing interface mockup.", pdf_text)
        self.assertLess(
            pdf_text.index("A three-tier architecture."),
            pdf_text.index("A testing interface mockup."),
        )

    def test_figure_list_ordering_is_generic_for_other_section_structures(self) -> None:
        image_buffer = BytesIO()
        Image.new("RGB", (4, 4), "white").save(image_buffer, format="PNG")
        image_bytes = image_buffer.getvalue()
        source = """# Research Report
## Background
Background text.
[[GENERATED_FIGURE:1]]
### Final Conclusion
Concluding text.
## 4. List of Figures
1. Figure 1: An outdated caption
"""
        pack = AssignmentFigurePack(
            matches=lambda _content, _instructions, _title: True,
            build=lambda _source, _instructions: (
                source,
                [
                    FigureDefinition(
                        1,
                        "A generic research diagram",
                        lambda: image_bytes,
                    )
                ],
            ),
        )
        with patch("app.services.assignment_figures._ASSIGNMENT_FIGURE_PACKS", []):
            register_assignment_figure_pack(pack)
            prepared, figures = prepare_assignment_figures(
                "Any assignment structure",
                None,
            )
        self.assertEqual(list(figures), [1])
        self.assertLess(
            prepared.index("## 4. List of Figures"),
            prepared.index("## Final Conclusion"),
        )
        self.assertIn("1. Figure 1: A generic research diagram", prepared)
        self.assertNotIn("An outdated caption", prepared)
        self.assertIn(
            "not genuine software screenshots or evidence of external software activity",
            prepared,
        )

    def test_saving_new_draft_updates_assignment_and_creates_first_version(self) -> None:
        content = "First saved draft"
        response = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": content},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["draft_content"], content)
        self.assertEqual(response.json()["version"]["version"], 1)

        with Session(self.engine) as db:
            assignment = db.get(Assignment, self.assignment_id)
            versions = db.scalars(
                select(AssignmentDraftVersion).where(
                    AssignmentDraftVersion.assignment_id == self.assignment_id
                )
            ).all()
            self.assertEqual(assignment.draft_content, content)
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0].content, content)

    def test_saving_unchanged_content_does_not_create_duplicate_version(self) -> None:
        content = "Unchanged draft content"
        first = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": content},
        )
        unchanged = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": content},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(unchanged.status_code, 200)
        self.assertIsNone(unchanged.json()["version"])

        with Session(self.engine) as db:
            versions = db.scalars(
                select(AssignmentDraftVersion).where(
                    AssignmentDraftVersion.assignment_id == self.assignment_id
                )
            ).all()
            self.assertEqual(len(versions), 1)

    def test_first_version_is_created_when_existing_draft_has_no_history(self) -> None:
        existing_draft = "Existing draft without version history"
        with Session(self.engine) as db:
            assignment = db.get(Assignment, self.assignment_id)
            assignment.draft_content = existing_draft
            db.commit()

        response = self.client.put(
            f"/api/assignments/{self.assignment_id}/draft",
            json={"content": existing_draft},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["draft_content"], existing_draft)
        self.assertEqual(response.json()["version"]["version"], 1)

    def test_exports_compatibly_version_existing_draft_without_history(self) -> None:
        existing_draft = "# Legacy draft\n\nExisting saved content."
        with Session(self.engine) as db:
            assignment = db.get(Assignment, self.assignment_id)
            assignment.draft_content = existing_draft
            db.commit()

        for file_format in ("pdf", "docx"):
            with self.subTest(file_format=file_format):
                response = self.client.get(
                    f"/api/assignments/{self.assignment_id}/documents/{file_format}"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["x-assignment-version"], "1")
        with Session(self.engine) as db:
            versions = db.scalars(
                select(AssignmentDraftVersion).where(
                    AssignmentDraftVersion.assignment_id == self.assignment_id
                )
            ).all()
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0].content, existing_draft)
            self.assertEqual(versions[0].source, "legacy")

    def test_export_rejects_genuinely_empty_draft(self) -> None:
        for file_format in ("pdf", "docx"):
            with self.subTest(file_format=file_format):
                response = self.client.get(
                    f"/api/assignments/{self.assignment_id}/documents/{file_format}"
                )
                self.assertEqual(response.status_code, 409)
                self.assertEqual(
                    response.json()["detail"],
                    "Save assignment content before exporting.",
                )

    def test_assignment_access_is_scoped_to_the_authenticated_student(self) -> None:
        with Session(self.engine) as db:
            other_user = User(full_name="Other Student", email="other@example.test")
            db.add(other_user)
            db.flush()
            other_assignment = Assignment(
                user_id=other_user.id,
                title="Private assignment",
                attachments=[],
                is_demo=False,
            )
            db.add(other_assignment)
            db.commit()
            other_assignment_id = other_assignment.id

        response = self.client.get(
            f"/api/assignments/{other_assignment_id}/workspace"
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
