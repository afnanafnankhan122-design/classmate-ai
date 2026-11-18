from datetime import UTC, datetime, timedelta
import unittest
from unittest.mock import patch

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models.course import Course
from app.models.google_account import GoogleAccount
from app.models.licensing import License, LicensingPolicy, Plan
from app.models.user import User
from app.services.classroom_scheduler import (
    create_classroom_scheduler,
    sync_connected_classrooms,
)
from app.services.entitlements import get_license_status


class ClassroomSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        now = datetime.now(UTC)
        with Session(self.engine) as db:
            db.add(
                LicensingPolicy(
                    id=1,
                    launch_at=now - timedelta(days=30),
                    grandfathering_days=30,
                )
            )
            plan = Plan(
                code="semester",
                name="Semester",
                amount_paisa=50000,
                duration_months=6,
                is_enabled=True,
            )
            db.add(plan)
            db.flush()
            self.plan_id = plan.id
            db.commit()
        self.account_ids: dict[str, int] = {}
        self.user_ids: dict[str, int] = {}

    def tearDown(self) -> None:
        self.engine.dispose()

    def add_student(
        self,
        email: str,
        expires_at: datetime,
        *,
        revoked: bool = False,
        cached_course: bool = False,
    ) -> int:
        now = datetime.now(UTC)
        with Session(self.engine) as db:
            user = User(full_name=email.split("@")[0], email=email)
            db.add(user)
            db.flush()
            db.add(
                License(
                    user_id=user.id,
                    plan_id=self.plan_id,
                    starts_at=now - timedelta(days=1),
                    expires_at=expires_at,
                    revoked_at=(now - timedelta(hours=1)) if revoked else None,
                    revoked_by_user_id=user.id if revoked else None,
                    revocation_reason="Test revocation" if revoked else None,
                )
            )
            account = GoogleAccount(
                user_id=user.id,
                google_sub=f"google-{user.id}",
                google_email=email,
                authorized_scopes=[],
            )
            db.add(account)
            if cached_course:
                db.add(
                    Course(
                        user_id=user.id,
                        google_course_id=f"course-{user.id}",
                        course_name="Cached Classroom",
                    )
                )
            db.commit()
            self.account_ids[email] = account.id
            self.user_ids[email] = user.id
            return account.id

    def run_scheduler_job(self) -> None:
        with patch(
            "app.services.classroom_scheduler.SessionLocal",
            side_effect=lambda: Session(self.engine),
        ):
            sync_connected_classrooms()

    def test_active_student_sync_executes(self) -> None:
        self.add_student(
            "active@example.test",
            datetime.now(UTC) + timedelta(days=1),
        )

        with (
            patch(
                "app.services.classroom_scheduler.get_classroom_credentials",
                return_value=object(),
            ) as get_credentials,
            patch("app.services.classroom_scheduler.sync_classroom_data") as sync,
        ):
            self.run_scheduler_job()

        get_credentials.assert_called_once()
        sync.assert_called_once()
        self.assertEqual(sync.call_args.args[1], self.user_ids["active@example.test"])

    def test_expired_student_sync_is_skipped_and_cached_data_is_preserved(self) -> None:
        self.add_student(
            "expired@example.test",
            datetime.now(UTC) - timedelta(seconds=1),
            cached_course=True,
        )

        with (
            patch("app.services.classroom_scheduler.get_classroom_credentials") as get_credentials,
            patch("app.services.classroom_scheduler.sync_classroom_data") as sync,
        ):
            self.run_scheduler_job()

        get_credentials.assert_not_called()
        sync.assert_not_called()
        with Session(self.engine) as db:
            cached = db.scalars(
                select(Course).where(Course.user_id == self.user_ids["expired@example.test"])
            ).all()
            self.assertEqual([course.course_name for course in cached], ["Cached Classroom"])

    def test_sync_job_created_while_active_rechecks_expired_license_at_execution(self) -> None:
        self.add_student(
            "scheduled@example.test",
            datetime.now(UTC) + timedelta(days=1),
        )
        with Session(self.engine) as db:
            license_record = db.scalar(
                select(License).where(
                    License.user_id == self.user_ids["scheduled@example.test"]
                )
            )
            license_record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

        with (
            patch("app.services.classroom_scheduler.get_classroom_credentials") as get_credentials,
            patch("app.services.classroom_scheduler.sync_classroom_data") as sync,
        ):
            self.run_scheduler_job()

        get_credentials.assert_not_called()
        sync.assert_not_called()

    def test_license_is_rechecked_after_credentials_are_loaded(self) -> None:
        self.add_student(
            "expires-during-setup@example.test",
            datetime.now(UTC) + timedelta(days=1),
        )

        def expire_license(*_args):
            with Session(self.engine) as db:
                license_record = db.scalar(
                    select(License).where(
                        License.user_id
                        == self.user_ids["expires-during-setup@example.test"]
                    )
                )
                license_record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                db.commit()
            return object()

        with (
            patch(
                "app.services.classroom_scheduler.get_classroom_credentials",
                side_effect=expire_license,
            ) as get_credentials,
            patch("app.services.classroom_scheduler.sync_classroom_data") as sync,
        ):
            self.run_scheduler_job()

        get_credentials.assert_called_once()
        sync.assert_not_called()

    def test_expired_student_does_not_block_active_student_and_renewal_resumes_sync(self) -> None:
        self.add_student(
            "expired-first@example.test",
            datetime.now(UTC) - timedelta(seconds=1),
        )
        self.add_student(
            "active-second@example.test",
            datetime.now(UTC) + timedelta(days=1),
        )
        with (
            patch(
                "app.services.classroom_scheduler.get_classroom_credentials",
                return_value=object(),
            ) as get_credentials,
            patch("app.services.classroom_scheduler.sync_classroom_data") as sync,
        ):
            self.run_scheduler_job()
            self.assertEqual(sync.call_count, 1)
            self.assertEqual(get_credentials.call_count, 1)

            with Session(self.engine) as db:
                expired = db.scalar(
                    select(License).where(
                        License.user_id == self.user_ids["expired-first@example.test"]
                    )
                )
                expired.expires_at = datetime.now(UTC) + timedelta(days=30)
                db.commit()

            self.run_scheduler_job()

        self.assertEqual(sync.call_count, 3)
        self.assertEqual(get_credentials.call_count, 3)

    def test_missing_user_and_revoked_license_are_skipped_safely(self) -> None:
        self.add_student(
            "revoked@example.test",
            datetime.now(UTC) + timedelta(days=1),
            revoked=True,
        )
        with Session(self.engine) as db:
            db.add(
                GoogleAccount(
                    user_id=99999,
                    google_sub="orphaned-google-account",
                    google_email="missing@example.test",
                    authorized_scopes=[],
                )
            )
            db.commit()

        with (
            patch("app.services.classroom_scheduler.get_classroom_credentials") as get_credentials,
            patch("app.services.classroom_scheduler.sync_classroom_data") as sync,
        ):
            self.run_scheduler_job()

        get_credentials.assert_not_called()
        sync.assert_not_called()

    def test_invalid_license_record_does_not_block_another_active_sync(self) -> None:
        self.add_student(
            "invalid-license@example.test",
            datetime.now(UTC) + timedelta(days=1),
        )
        self.add_student(
            "valid-license@example.test",
            datetime.now(UTC) + timedelta(days=1),
        )

        def license_status_for_student(db, user):
            if user.email == "invalid-license@example.test":
                raise ValueError("Invalid license record")
            return get_license_status(db, user)

        with (
            patch(
                "app.services.classroom_scheduler.get_license_status",
                side_effect=license_status_for_student,
            ),
            patch(
                "app.services.classroom_scheduler.get_classroom_credentials",
                return_value=object(),
            ) as get_credentials,
            patch("app.services.classroom_scheduler.sync_classroom_data") as sync,
        ):
            self.run_scheduler_job()

        self.assertEqual(get_credentials.call_count, 1)
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(sync.call_args.args[1], self.user_ids["valid-license@example.test"])

    def test_scheduler_uses_one_recurring_job_per_service(self) -> None:
        scheduler: BackgroundScheduler = create_classroom_scheduler()
        self.assertEqual(
            {job.id for job in scheduler.get_jobs()},
            {"classmate-classroom-sync", "classmate-due-assignment-scan"},
        )


if __name__ == "__main__":
    unittest.main()
