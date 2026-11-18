from datetime import UTC, datetime, timedelta
import unittest
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError
import httplib2
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.dependencies import get_db
from app.core.auth_security import auth_rate_limiter
from app.main import app
from app.models.assignment import Assignment, AssignmentDraftVersion, AssignmentExport
from app.models.approval import Approval
from app.models.course import Course
from app.models.google_account import GoogleAccount
from app.models.licensing import License, LicensingPolicy, Plan
from app.models.notification import Notification
from app.models.submission import Submission
from app.models.user import User
from app.services.assignment_processing import (
    due_date_in_karachi,
    process_due_assignments,
)
from app.services.google_oauth import (
    CLASSROOM_READ_SCOPES,
    CLASSROOM_WRITE_SCOPES,
    DRIVE_FILE_SCOPE,
)
from app.services.google_submission import (
    GoogleSubmissionError,
    SubmissionPrerequisiteError,
    submit_approved_assignment,
)
from app.services.entitlements import get_license_status


class AssignmentProcessingTests(unittest.TestCase):
    def setUp(self) -> None:
        auth_rate_limiter.reset("register:testclient")
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            self.user = User(full_name="Processing Student", email="processing@example.com")
            db.add(self.user)
            db.commit()
            self.user_id = self.user.id
            self.plan = Plan(
                code="semester",
                name="Semester",
                amount_paisa=50000,
                duration_months=6,
                is_enabled=True,
            )
            db.add(self.plan)
            db.commit()
            self.plan_id = self.plan.id

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        auth_rate_limiter.reset("register:testclient")
        self.engine.dispose()

    def add_assignment(
        self,
        db: Session,
        title: str,
        due_date: datetime | None,
        **fields,
    ) -> Assignment:
        assignment = Assignment(
            user_id=self.user_id,
            title=title,
            description="Answer the question using the supplied instructions.",
            due_date=due_date,
            attachments=[],
            is_demo=False,
            **fields,
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
        return assignment

    def set_license(self, expires_at: datetime) -> None:
        now = datetime.now(UTC)
        with Session(self.engine) as db:
            policy = db.get(LicensingPolicy, 1)
            if policy is None:
                db.add(
                    LicensingPolicy(
                        id=1,
                        launch_at=now - timedelta(days=30),
                        grandfathering_days=30,
                    )
                )
            license_record = db.scalar(
                select(License).where(License.user_id == self.user_id)
            )
            if license_record is None:
                db.add(
                    License(
                        user_id=self.user_id,
                        plan_id=self.plan_id,
                        starts_at=now - timedelta(days=1),
                        expires_at=expires_at,
                    )
                )
            else:
                license_record.starts_at = now - timedelta(days=1)
                license_record.expires_at = expires_at
                license_record.revoked_at = None
                license_record.revoked_by_user_id = None
                license_record.revocation_reason = None
            db.commit()

    def test_only_due_today_assignments_are_processed_once(self) -> None:
        now = datetime(2025, 3, 10, 12, 0, tzinfo=UTC)
        with Session(self.engine) as db:
            due_today = self.add_assignment(db, "Today", datetime(2025, 3, 10, 14))
            future = self.add_assignment(db, "Future", datetime(2025, 3, 11, 12))
            overdue = self.add_assignment(db, "Overdue", datetime(2025, 3, 9, 12))
            missing = self.add_assignment(db, "Undated", None)
            submitted = self.add_assignment(
                db,
                "Already submitted",
                datetime(2025, 3, 10, 14),
                submission_status="turned_in",
            )
            with (
                patch(
                    "app.services.assignment_processing.create_assignment_suggestion",
                    return_value="# Answer\n\nGenerated on the due date.",
                ) as generate,
                patch(
                    "app.services.assignment_processing.make_pdf",
                    return_value=b"%PDF-1.4 test document",
                ),
            ):
                claimed = process_due_assignments(db, now)
                self.assertEqual(claimed, 1)
                self.assertEqual(process_due_assignments(db, now), 0)

            self.assertEqual(generate.call_count, 1)
            self.assertEqual(due_today.processing_status, "ready_for_review")
            self.assertEqual(future.processing_status, "pending")
            self.assertEqual(overdue.processing_status, "overdue")
            self.assertEqual(missing.processing_status, "pending")
            self.assertEqual(submitted.processing_status, "pending")
            self.assertEqual(due_today.draft_content, "# Answer\n\nGenerated on the due date.")
            self.assertEqual(
                db.scalar(
                    select(AssignmentDraftVersion).where(
                        AssignmentDraftVersion.assignment_id == due_today.id
                    )
                ).content,
                due_today.draft_content,
            )
            self.assertIsNotNone(
                db.scalar(
                    select(AssignmentExport).where(
                        AssignmentExport.assignment_id == due_today.id,
                        AssignmentExport.file_format == "pdf",
                    )
                ).file_content
            )
            self.assertEqual(
                len(
                    db.scalars(
                        select(Notification).where(
                            Notification.assignment_id == due_today.id,
                            Notification.category == "assignment_ready",
                        )
                    ).all()
                ),
                1,
            )

    def test_expired_student_due_assignment_is_skipped_without_a_claim(self) -> None:
        now = datetime(2025, 3, 10, 12, 0, tzinfo=UTC)
        self.set_license(datetime.now(UTC) - timedelta(seconds=1))
        with Session(self.engine) as db:
            assignment = self.add_assignment(
                db,
                "Expired student's work",
                datetime(2025, 3, 10, 14),
            )
            assignment_id = assignment.id
        with (
            patch("app.services.assignment_processing.create_assignment_suggestion") as generate,
            patch("app.services.assignment_processing.make_pdf") as make_pdf,
            Session(self.engine) as db,
        ):
            self.assertEqual(process_due_assignments(db, now), 0)
        generate.assert_not_called()
        make_pdf.assert_not_called()
        with Session(self.engine) as db:
            assignment = db.get(Assignment, assignment_id)
            self.assertEqual(assignment.processing_status, "pending")
            self.assertEqual(assignment.processing_attempts, 0)
            self.assertIsNone(assignment.draft_content)

    def test_revoked_student_due_assignment_is_skipped_safely(self) -> None:
        self.set_license(datetime.now(UTC) + timedelta(days=1))
        with Session(self.engine) as db:
            administrator = User(
                full_name="License Administrator",
                email="license-admin@example.com",
                is_admin=True,
            )
            db.add(administrator)
            db.flush()
            license_record = db.scalar(
                select(License).where(License.user_id == self.user_id)
            )
            license_record.revoked_at = datetime.now(UTC)
            license_record.revoked_by_user_id = administrator.id
            license_record.revocation_reason = "Testing revoked entitlement"
            assignment = self.add_assignment(
                db,
                "Revoked student's work",
                datetime(2025, 3, 10, 14),
            )
            assignment_id = assignment.id
        with (
            patch("app.services.assignment_processing.create_assignment_suggestion") as generate,
            Session(self.engine) as db,
        ):
            self.assertEqual(
                process_due_assignments(
                    db,
                    datetime(2025, 3, 10, 12, 0, tzinfo=UTC),
                ),
                0,
            )
        generate.assert_not_called()
        with Session(self.engine) as db:
            self.assertEqual(db.get(Assignment, assignment_id).processing_attempts, 0)

    def test_job_eligible_before_expiry_is_checked_again_when_scan_executes(self) -> None:
        self.set_license(datetime.now(UTC) + timedelta(days=1))
        with Session(self.engine) as db:
            assignment = self.add_assignment(
                db,
                "Scheduled while active",
                datetime(2025, 3, 10, 14),
            )
            assignment_id = assignment.id
        self.set_license(datetime.now(UTC) - timedelta(seconds=1))
        with (
            patch("app.services.assignment_processing.create_assignment_suggestion") as generate,
            Session(self.engine) as db,
        ):
            self.assertEqual(
                process_due_assignments(db, datetime(2025, 3, 10, 12, tzinfo=UTC)),
                0,
            )
        generate.assert_not_called()
        with Session(self.engine) as db:
            self.assertEqual(db.get(Assignment, assignment_id).processing_attempts, 0)

    def test_retries_recheck_license_and_resume_after_renewal(self) -> None:
        fake_now = datetime(2025, 3, 10, 12, 0, tzinfo=UTC)
        self.set_license(datetime.now(UTC) + timedelta(days=1))
        with Session(self.engine) as db:
            assignment = self.add_assignment(
                db,
                "Retry after renewal",
                datetime(2025, 3, 10, 14),
            )
            assignment_id = assignment.id
        with (
            patch(
                "app.services.assignment_processing.create_assignment_suggestion",
                side_effect=[
                    RuntimeError("temporary generation failure"),
                    "# Ready\n\nGenerated after renewal.",
                ],
            ) as generate,
            patch(
                "app.services.assignment_processing.make_pdf",
                return_value=b"%PDF-1.4 renewed",
            ),
        ):
            with Session(self.engine) as db:
                self.assertEqual(process_due_assignments(db, fake_now), 1)
            with Session(self.engine) as db:
                failed = db.get(Assignment, assignment_id)
                self.assertEqual(failed.processing_status, "failed")
                self.assertEqual(failed.processing_attempts, 1)

            self.set_license(datetime.now(UTC) - timedelta(seconds=1))
            with Session(self.engine) as db:
                self.assertEqual(
                    process_due_assignments(db, fake_now + timedelta(minutes=6)),
                    0,
                )
            self.assertEqual(generate.call_count, 1)
            with Session(self.engine) as db:
                waiting = db.get(Assignment, assignment_id)
                self.assertEqual(waiting.processing_status, "failed")
                self.assertEqual(waiting.processing_attempts, 1)

            self.set_license(datetime.now(UTC) + timedelta(days=30))
            with Session(self.engine) as db:
                self.assertEqual(
                    process_due_assignments(db, fake_now + timedelta(minutes=7)),
                    1,
                )
            self.assertEqual(generate.call_count, 2)

        with Session(self.engine) as db:
            assignment = db.get(Assignment, assignment_id)
            self.assertEqual(assignment.processing_status, "ready_for_review")
            self.assertIn("Generated after renewal.", assignment.draft_content)

    def test_expired_student_does_not_block_another_active_students_assignment(self) -> None:
        self.set_license(datetime.now(UTC) - timedelta(seconds=1))
        with Session(self.engine) as db:
            expired = self.add_assignment(
                db,
                "Expired student's assignment",
                datetime(2025, 3, 10, 14),
            )
            active_user = User(
                full_name="Active Student",
                email="active-processing@example.com",
            )
            db.add(active_user)
            db.flush()
            now = datetime.now(UTC)
            db.add(
                License(
                    user_id=active_user.id,
                    plan_id=self.plan_id,
                    starts_at=now - timedelta(days=1),
                    expires_at=now + timedelta(days=30),
                )
            )
            active_assignment = Assignment(
                user_id=active_user.id,
                title="Active student's assignment",
                description="Instructions",
                due_date=datetime(2025, 3, 10, 14),
                attachments=[],
                is_demo=False,
            )
            db.add(active_assignment)
            db.commit()
            expired_id = expired.id
            active_id = active_assignment.id
        with (
            patch(
                "app.services.assignment_processing.create_assignment_suggestion",
                return_value="# Active\n\nActive student's generated work.",
            ) as generate,
            patch(
                "app.services.assignment_processing.make_pdf",
                return_value=b"%PDF-1.4 active",
            ),
            Session(self.engine) as db,
        ):
            self.assertEqual(
                process_due_assignments(
                    db,
                    datetime(2025, 3, 10, 12, 0, tzinfo=UTC),
                ),
                1,
            )
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(generate.call_args.kwargs["title"], "Active student's assignment")
        with Session(self.engine) as db:
            self.assertEqual(db.get(Assignment, expired_id).processing_attempts, 0)
            self.assertEqual(
                db.get(Assignment, active_id).processing_status,
                "ready_for_review",
            )

    def test_missing_assignment_owner_is_skipped_safely(self) -> None:
        with Session(self.engine) as db:
            assignment = Assignment(
                user_id=9999,
                title="Orphaned assignment",
                description="Instructions",
                due_date=datetime(2025, 3, 10, 14),
                attachments=[],
                is_demo=False,
            )
            db.add(assignment)
            db.commit()
            assignment_id = assignment.id
        with (
            patch("app.services.assignment_processing.create_assignment_suggestion") as generate,
            Session(self.engine) as db,
        ):
            self.assertEqual(
                process_due_assignments(
                    db,
                    datetime(2025, 3, 10, 12, 0, tzinfo=UTC),
                ),
                0,
            )
        generate.assert_not_called()
        with Session(self.engine) as db:
            self.assertEqual(db.get(Assignment, assignment_id).processing_attempts, 0)

    def test_invalid_license_check_does_not_block_another_active_assignment(self) -> None:
        fake_now = datetime(2025, 3, 10, 12, 0, tzinfo=UTC)
        self.set_license(datetime.now(UTC) + timedelta(days=30))
        with Session(self.engine) as db:
            invalid_assignment = self.add_assignment(
                db,
                "Invalid license owner",
                datetime(2025, 3, 10, 14),
            )
            active_user = User(
                full_name="Other Active Student",
                email="other-active-processing@example.com",
            )
            db.add(active_user)
            db.flush()
            now = datetime.now(UTC)
            db.add(
                License(
                    user_id=active_user.id,
                    plan_id=self.plan_id,
                    starts_at=now - timedelta(days=1),
                    expires_at=now + timedelta(days=30),
                )
            )
            active_assignment = Assignment(
                user_id=active_user.id,
                title="Valid license owner",
                description="Instructions",
                due_date=datetime(2025, 3, 10, 14),
                attachments=[],
                is_demo=False,
            )
            db.add(active_assignment)
            db.commit()
            invalid_assignment_id = invalid_assignment.id
            active_assignment_id = active_assignment.id

        def license_status_for_student(db, user):
            if user.id == self.user_id:
                raise ValueError("Invalid license record")
            return get_license_status(db, user)

        with (
            patch(
                "app.services.assignment_processing.get_license_status",
                side_effect=license_status_for_student,
            ),
            patch(
                "app.services.assignment_processing.create_assignment_suggestion",
                return_value="# Active\n\nGenerated for the active student.",
            ) as generate,
            patch(
                "app.services.assignment_processing.make_pdf",
                return_value=b"%PDF-1.4 active",
            ),
            Session(self.engine) as db,
        ):
            self.assertEqual(process_due_assignments(db, fake_now), 1)

        self.assertEqual(generate.call_count, 1)
        self.assertEqual(generate.call_args.kwargs["title"], "Valid license owner")
        with Session(self.engine) as db:
            self.assertEqual(
                db.get(Assignment, invalid_assignment_id).processing_attempts,
                0,
            )
            self.assertEqual(
                db.get(Assignment, active_assignment_id).processing_status,
                "ready_for_review",
            )

    def test_due_day_comparison_uses_asia_karachi(self) -> None:
        karachi = ZoneInfo("Asia/Karachi")
        instant = datetime(2025, 3, 10, 20, 0, tzinfo=UTC)
        self.assertEqual(due_date_in_karachi(instant), datetime(2025, 3, 11).date())
        self.assertEqual(due_date_in_karachi(datetime(2025, 3, 10, 20)), datetime(2025, 3, 11).date())
        self.assertEqual(instant.astimezone(karachi).date(), datetime(2025, 3, 11).date())
        self.assertIsNone(due_date_in_karachi(None))

    def test_stale_claim_is_recovered_after_downtime_without_losing_saved_text(self) -> None:
        now = datetime(2025, 3, 10, 12, 0, tzinfo=UTC)
        with Session(self.engine) as db:
            assignment = self.add_assignment(
                db,
                "Recovered",
                datetime(2025, 3, 10, 14),
                draft_content="Student-saved work",
                processing_status="processing",
                processing_started_at=(now - timedelta(minutes=20)).replace(tzinfo=None),
                processing_claim_id="stale-claim",
            )
            with (
                patch("app.services.assignment_processing.create_assignment_suggestion") as generate,
                patch(
                    "app.services.assignment_processing.make_pdf",
                    return_value=b"%PDF-1.4 recovery",
                ),
            ):
                self.assertEqual(process_due_assignments(db, now), 1)
            generate.assert_not_called()
            self.assertEqual(assignment.processing_status, "ready_for_review")
            self.assertEqual(assignment.draft_content, "Student-saved work")
            self.assertIsNone(assignment.processing_claim_id)

    def test_submission_requires_approval_and_never_submits_during_processing(self) -> None:
        def override_get_db():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app, base_url="http://localhost:8000")
        try:
            response = client.post(
                "/api/auth/register",
                json={
                    "full_name": "Approval Student",
                    "email": "approval@example.com",
                    "password": "SecureStudent123!",
                    "confirm_password": "SecureStudent123!",
                    "terms_accepted": True,
                },
            )
            self.assertEqual(response.status_code, 201)
            with Session(self.engine) as db:
                user = db.scalar(select(User).where(User.email == "approval@example.com"))
                course = Course(
                    user_id=user.id,
                    google_course_id="google-course",
                    course_name="Test Course",
                )
                db.add(course)
                db.flush()
                assignment = Assignment(
                    user_id=user.id,
                    course_id=course.id,
                    google_assignment_id="google-assignment",
                    title="Needs approval",
                    due_date=datetime(2025, 3, 10, 14),
                    description="Write a short response.",
                    draft_content=None,
                    attachments=[],
                    is_demo=False,
                )
                db.add(assignment)
                db.commit()
                assignment_id = assignment.id

            client.put(
                f"/api/assignments/{assignment_id}/draft",
                json={"content": "The student's final response."},
            )
            with patch(
                "app.api.routes.assignments.make_pdf",
                return_value=b"%PDF-1.4 approval test",
            ):
                pdf_response = client.get(
                    f"/api/assignments/{assignment_id}/documents/pdf"
                )
            self.assertEqual(pdf_response.status_code, 200)
            saved_export = client.get(
                f"/api/assignments/{assignment_id}/exports/"
                f"{pdf_response.headers['x-assignment-export']}"
            )
            self.assertEqual(saved_export.status_code, 200)
            self.assertEqual(saved_export.content, b"%PDF-1.4 approval test")

            blocked = client.post(f"/api/assignments/{assignment_id}/submit")
            self.assertEqual(blocked.status_code, 409)

            approved = client.post(f"/api/assignments/{assignment_id}/approve")
            self.assertEqual(approved.status_code, 200)
            with patch("app.api.routes.assignments.submit_approved_assignment") as submit:
                submit.return_value = {
                    "status": "submitted",
                    "google_submission_id": "verified-id",
                }
                submitted = client.post(f"/api/assignments/{assignment_id}/submit")
                self.assertEqual(submitted.status_code, 200)
                self.assertEqual(submitted.json()["status"], "submitted")
                submit.assert_called_once()
        finally:
            client.close()

    def prepare_google_submission(self, db: Session) -> Assignment:
        course = Course(
            user_id=self.user_id,
            google_course_id="google-course",
            course_name="Test Course",
        )
        db.add(course)
        db.flush()
        assignment = Assignment(
            user_id=self.user_id,
            course_id=course.id,
            google_assignment_id="google-assignment",
            title="Approved assignment",
            description="Complete the task.",
            draft_content="Approved content",
            attachments=[],
            is_demo=False,
        )
        db.add(assignment)
        db.flush()
        version = AssignmentDraftVersion(
            assignment_id=assignment.id,
            version=1,
            content="Approved content",
            source="student",
        )
        db.add(version)
        db.flush()
        db.add(
            AssignmentExport(
                assignment_id=assignment.id,
                draft_version_id=version.id,
                file_format="pdf",
                file_content=b"%PDF-1.4 approved",
            )
        )
        db.add(
            Approval(
                assignment_id=assignment.id,
                document_version=1,
                approval_status="approved",
            )
        )
        db.add(
            GoogleAccount(
                user_id=self.user_id,
                google_sub="google-sub",
                google_email="processing@example.com",
                authorized_scopes=[
                    CLASSROOM_READ_SCOPES[0],
                    *CLASSROOM_WRITE_SCOPES,
                    DRIVE_FILE_SCOPE,
                ],
            )
        )
        db.commit()
        return assignment

    def make_google_api_mocks(self, verified_state: str):
        classroom = MagicMock()
        drive = MagicMock()
        classroom_submissions = classroom.courses.return_value.courseWork.return_value.studentSubmissions.return_value
        classroom_submissions.list.return_value.execute.return_value = {
            "studentSubmissions": [
                {
                    "id": "submission-1",
                    "state": "CREATED",
                    "assignmentSubmission": {"attachments": []},
                }
            ]
        }
        classroom_submissions.modifyAttachments.return_value.execute.return_value = {}
        classroom_submissions.turnIn.return_value.execute.return_value = {}
        classroom_submissions.get.return_value.execute.return_value = {
            "id": "submission-1",
            "state": verified_state,
        }
        drive.files.return_value.list.return_value.execute.return_value = {"files": []}
        drive.files.return_value.create.return_value.execute.return_value = {"id": "drive-file-1"}
        return classroom, drive, classroom_submissions

    def test_google_submission_is_confirmed_before_success_is_returned(self) -> None:
        with Session(self.engine) as db:
            assignment = self.prepare_google_submission(db)
            classroom, drive, google_submissions = self.make_google_api_mocks("TURNED_IN")
            with (
                patch("app.services.google_submission.get_classroom_credentials"),
                patch(
                    "app.services.google_submission.build",
                    side_effect=[classroom, drive],
                ),
            ):
                result = submit_approved_assignment(db, assignment)
            self.assertEqual(result["status"], "submitted")
            google_submissions.get.assert_called_once()
            google_submissions.turnIn.assert_called_once()
            self.assertEqual(assignment.submission_status, "turned_in")
            submission = db.scalar(
                select(Submission).where(
                    Submission.assignment_id == assignment.id,
                    Submission.draft_version_id == 1,
                )
            )
            self.assertEqual(submission.google_file_id, "drive-file-1")

    def test_insufficient_google_permission_requests_reconnection(self) -> None:
        with Session(self.engine) as db:
            assignment = self.prepare_google_submission(db)
            classroom = MagicMock()
            response = httplib2.Response({"status": "403"})
            error = HttpError(
                response,
                b'{"error":{"errors":[{"reason":"insufficientPermissions"}]}}',
            )
            (
                classroom.courses.return_value.courseWork.return_value
                .studentSubmissions.return_value.list.return_value.execute.side_effect
            ) = error

            with (
                patch("app.services.google_submission.get_classroom_credentials"),
                patch("app.services.google_submission.build", return_value=classroom),
                self.assertRaisesRegex(SubmissionPrerequisiteError, "Reconnect Google"),
            ):
                submit_approved_assignment(db, assignment)

    def test_google_submission_does_not_report_success_without_verified_state(self) -> None:
        with Session(self.engine) as db:
            assignment = self.prepare_google_submission(db)
            classroom, drive, google_submissions = self.make_google_api_mocks("CREATED")
            with (
                patch("app.services.google_submission.get_classroom_credentials"),
                patch(
                    "app.services.google_submission.build",
                    side_effect=[classroom, drive],
                ),
                self.assertRaises(GoogleSubmissionError),
            ):
                submit_approved_assignment(db, assignment)
            self.assertEqual(assignment.submission_status, "not_started")
            google_submissions.get.assert_called_once()

    def test_google_submission_requires_all_write_scopes_before_api_calls(self) -> None:
        with Session(self.engine) as db:
            assignment = self.prepare_google_submission(db)
            account = db.scalar(
                select(GoogleAccount).where(GoogleAccount.user_id == self.user_id)
            )
            account.authorized_scopes = [DRIVE_FILE_SCOPE, *CLASSROOM_READ_SCOPES]
            db.commit()
            with (
                patch("app.services.google_submission.build") as build,
                self.assertRaises(SubmissionPrerequisiteError),
            ):
                submit_approved_assignment(db, assignment)
            build.assert_not_called()
