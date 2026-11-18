from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.auth import get_current_user
from app.core.auth_security import hash_password
from app.core.config import settings
from app.database.base import Base
from app.database.dependencies import get_db
from app.main import app
from app.models.licensing import (
    License,
    LicenseAuditLog,
    LicensingPolicy,
    Payment,
    PaymentMethod,
    Plan,
)
from app.models.assignment import Assignment
from app.models.course import Course
from app.models.google_account import GoogleAccount
from app.models.user import User
from app.services.calendar_months import add_calendar_months
from app.services.entitlements import get_license_status


class LicensingApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="classmate-receipts-test-")
        self.original_receipt_dir = settings.payment_receipt_dir
        settings.payment_receipt_dir = Path(self.temp_dir.name)

        with Session(self.engine) as db:
            self.student = User(
                full_name="Test Student",
                email="student@example.test",
                hashed_password=hash_password("StudentSecure123!"),
            )
            self.other_student = User(
                full_name="Other Student",
                email="other@example.test",
                hashed_password=hash_password("OtherSecure123!"),
            )
            self.admin = User(
                full_name="Test Admin",
                email="admin@example.test",
                hashed_password=hash_password("AdminSecure123!"),
                is_admin=True,
                is_verified=True,
            )
            db.add_all([self.student, self.other_student, self.admin])
            db.flush()
            self.plan = Plan(
                code="semester",
                name="Semester",
                amount_paisa=50000,
                currency="PKR",
                duration_months=6,
                is_enabled=True,
            )
            db.add(self.plan)
            db.flush()
            self.method = PaymentMethod(
                code="easypaisa",
                name="Easypaisa",
                account_holder_name="Verified Holder",
                account_number="0000000000",
                instructions="Use the transaction reference from your receipt.",
                is_enabled=True,
                details_verified_at=datetime.now(UTC),
                details_verified_by_user_id=self.admin.id,
            )
            db.add_all(
                [
                    self.method,
                    LicensingPolicy(id=1, grandfathering_days=30),
                ]
            )
            db.commit()
            db.refresh(self.student)
            db.refresh(self.other_student)
            db.refresh(self.admin)
            db.refresh(self.plan)
            db.refresh(self.method)
            self.student_id = self.student.id
            self.other_student_id = self.other_student.id
            self.admin_id = self.admin.id
            self.plan_id = self.plan.id
            self.method_id = self.method.id

        self.current_user = self.student

        def override_get_db():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides.clear()
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: self.current_user
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()
        settings.payment_receipt_dir = self.original_receipt_dir
        self.temp_dir.cleanup()
        self.engine.dispose()

    @staticmethod
    def _png() -> bytes:
        buffer = BytesIO()
        Image.new("RGB", (4, 4), color=(30, 80, 120)).save(buffer, format="PNG")
        return buffer.getvalue()

    def _submit(self, reference: str = "TXN-12345", key: str = "payment-key-0001"):
        return self.client.post(
            "/api/payments/submit",
            headers={"Idempotency-Key": key},
            data={
                "payment_method_id": str(self.method_id),
                "transaction_reference": reference,
            },
            files={"receipt": ("receipt.png", self._png(), "image/png")},
        )

    def _approve(self, payment_id: int):
        self.current_user = self.admin
        response = self.client.post(
            f"/api/admin/payments/{payment_id}/approve",
            json={"password": "AdminSecure123!"},
        )
        self.current_user = self.student
        return response

    def test_successful_submission_stays_pending_without_license(self) -> None:
        response = self._submit()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "pending")
        self.assertTrue(response.json()["receipt_available"])
        with Session(self.engine) as db:
            self.assertEqual(len(db.scalars(select(Payment)).all()), 1)
            self.assertEqual(db.scalar(select(License.id)), None)
            self.assertEqual(db.scalar(select(LicenseAuditLog.action)), "payment_submitted")

    def test_missing_reference_is_rejected(self) -> None:
        response = self._submit(reference="")
        self.assertEqual(response.status_code, 422)

    def test_invalid_receipt_content_is_rejected(self) -> None:
        response = self.client.post(
            "/api/payments/submit",
            data={
                "payment_method_id": str(self.method_id),
                "transaction_reference": "TXN-INVALID",
            },
            files={"receipt": ("fake.png", b"not an image", "image/png")},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(list(Path(self.temp_dir.name).iterdir()), [])

    def test_idempotent_retry_and_duplicate_pending_submission(self) -> None:
        first = self._submit()
        retry = self._submit()
        duplicate = self._submit(reference="TXN-54321", key="payment-key-0002")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(first.json()["id"], retry.json()["id"])
        self.assertEqual(duplicate.status_code, 409)

    def test_student_cannot_approve_payment_or_access_other_receipt(self) -> None:
        submitted = self._submit()
        payment_id = submitted.json()["id"]
        approval = self.client.post(
            f"/api/admin/payments/{payment_id}/approve",
            json={"password": "AdminSecure123!"},
        )
        receipt = self.client.get(f"/api/payments/{payment_id}/receipt")
        self.assertEqual(approval.status_code, 403)
        self.assertEqual(receipt.status_code, 200)

        self.current_user = self.other_student
        cross_user_receipt = self.client.get(f"/api/payments/{payment_id}/receipt")
        self.assertEqual(cross_user_receipt.status_code, 404)

    def test_admin_can_approve_once_and_activate_license(self) -> None:
        submitted = self._submit()
        payment_id = submitted.json()["id"]
        before = datetime.now(UTC)
        approval = self._approve(payment_id)
        self.assertEqual(approval.status_code, 200)
        self.assertFalse(approval.json()["already_approved"])
        self.assertIsNotNone(approval.json()["payment"]["license_started_at"])
        self.assertIsNotNone(approval.json()["payment"]["license_expires_at"])
        with Session(self.engine) as db:
            license_record = db.scalar(select(License).where(License.user_id == self.student_id))
            self.assertIsNotNone(license_record)
            self.assertGreaterEqual(license_record.starts_at.replace(tzinfo=UTC), before)
            initial_expiry = license_record.expires_at
        retry = self._approve(payment_id)
        self.assertTrue(retry.json()["already_approved"])
        with Session(self.engine) as db:
            license_record = db.scalar(select(License).where(License.user_id == self.student_id))
            self.assertEqual(license_record.expires_at, initial_expiry)

    def test_admin_can_reject_with_reason_and_student_can_resubmit(self) -> None:
        submitted = self._submit()
        payment_id = submitted.json()["id"]
        self.current_user = self.admin
        missing_reason = self.client.post(
            f"/api/admin/payments/{payment_id}/reject",
            json={"password": "AdminSecure123!"},
        )
        self.assertEqual(missing_reason.status_code, 422)
        rejected = self.client.post(
            f"/api/admin/payments/{payment_id}/reject",
            json={"password": "AdminSecure123!", "reason": "Reference could not be verified."},
        )
        self.assertEqual(rejected.status_code, 200)
        self.current_user = self.student
        history = self.client.get("/api/payments/my")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["payments"][0]["rejection_reason"], "Reference could not be verified.")
        resubmitted = self._submit(reference="TXN-67890", key="payment-key-0002")
        self.assertEqual(resubmitted.status_code, 201)

    def test_unauthorized_admin_access_is_rejected(self) -> None:
        response = self.client.get("/api/admin/payments")
        self.assertEqual(response.status_code, 403)

    def test_payment_method_cannot_be_enabled_without_explicit_verification(self) -> None:
        self.current_user = self.admin
        body = {
            "password": "AdminSecure123!",
            "name": "Easypaisa",
            "account_holder_name": "Verified Holder",
            "account_number": "0000000000",
            "instructions": "Pay PKR 500 and enter your reference.",
            "is_enabled": True,
            "confirm_details_verified": False,
        }
        rejected = self.client.patch(
            f"/api/admin/payment-methods/{self.method_id}",
            json=body,
        )
        self.assertEqual(rejected.status_code, 422)
        body["confirm_details_verified"] = True
        enabled = self.client.patch(
            f"/api/admin/payment-methods/{self.method_id}",
            json=body,
        )
        self.assertEqual(enabled.status_code, 200)

    def test_public_registration_cannot_grant_admin_role(self) -> None:
        response = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "Public Student",
                "email": "public-student@example.test",
                "password": "PublicStudent123!",
                "confirm_password": "PublicStudent123!",
                "terms_accepted": True,
                "is_admin": True,
            },
        )
        self.assertIn(response.status_code, {201, 422})
        with Session(self.engine) as db:
            public_user = db.scalar(
                select(User).where(User.email == "public-student@example.test")
            )
            if public_user is not None:
                self.assertFalse(public_user.is_admin)

    def test_database_defaults_do_not_grant_admin_or_enable_payment_methods(self) -> None:
        with Session(self.engine) as db:
            db.execute(
                text(
                    "INSERT INTO users "
                    "(full_name, email, auth_provider, auth_version, is_verified, created_at, updated_at) "
                    "VALUES ('Default User', 'default@example.test', 'email', 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            db.execute(
                text("INSERT INTO payment_methods (code, name) VALUES ('default_disabled', 'Disabled')")
            )
            db.commit()
            user = db.scalar(select(User).where(User.email == "default@example.test"))
            method = db.scalar(
                select(PaymentMethod).where(PaymentMethod.code == "default_disabled")
            )
            self.assertFalse(user.is_admin)
            self.assertFalse(method.is_enabled)

    def test_active_renewal_extends_existing_expiry(self) -> None:
        first = self._submit()
        self.assertEqual(self._approve(first.json()["id"]).status_code, 200)
        with Session(self.engine) as db:
            existing = db.scalar(select(License).where(License.user_id == self.student_id))
            old_expiry = existing.expires_at.replace(tzinfo=UTC)
        second = self._submit(reference="TXN-RENEW-1", key="payment-key-0002")
        self.assertEqual(second.status_code, 201)
        approval = self._approve(second.json()["id"])
        self.assertEqual(approval.status_code, 200)
        with Session(self.engine) as db:
            license_record = db.scalar(select(License).where(License.user_id == self.student_id))
            self.assertEqual(
                license_record.expires_at.replace(tzinfo=UTC),
                add_calendar_months(old_expiry, 6),
            )

    def test_expired_license_renewal_starts_at_approval(self) -> None:
        with Session(self.engine) as db:
            db.add(
                License(
                    user_id=self.student_id,
                    plan_id=self.plan_id,
                    starts_at=datetime.now(UTC) - timedelta(days=400),
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
            db.commit()
        submitted = self._submit()
        before_approval = datetime.now(UTC)
        self.assertEqual(self._approve(submitted.json()["id"]).status_code, 200)
        with Session(self.engine) as db:
            license_record = db.scalar(select(License).where(License.user_id == self.student_id))
            starts_at = license_record.starts_at.replace(tzinfo=UTC)
            self.assertGreaterEqual(starts_at, before_approval)

    def test_reauthentication_is_required_for_approval(self) -> None:
        submitted = self._submit()
        self.current_user = self.admin
        response = self.client.post(
            f"/api/admin/payments/{submitted.json()['id']}/approve",
            json={"password": "incorrect"},
        )
        self.assertEqual(response.status_code, 401)

    def test_expired_student_keeps_cached_classroom_data_but_cannot_sync(self) -> None:
        launch_at = datetime.now(UTC) - timedelta(days=31)
        with Session(self.engine) as db:
            student = db.get(User, self.student_id)
            policy = db.get(LicensingPolicy, 1)
            assert student is not None
            assert policy is not None
            student.created_at = launch_at - timedelta(days=365)
            policy.launch_at = launch_at
            course = Course(
                user_id=self.student_id,
                google_course_id="cached-course",
                course_name="Cached course",
                is_active=True,
            )
            db.add(course)
            db.add(
                GoogleAccount(
                    user_id=self.student_id,
                    google_sub="cached-google-user",
                    google_email="student@example.test",
                )
            )
            db.add(
                License(
                    user_id=self.student_id,
                    plan_id=self.plan_id,
                    starts_at=datetime.now(UTC) - timedelta(days=400),
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
            db.commit()
        from app.api.routes import classroom

        with patch.object(classroom, "sync_classroom_data") as sync:
            cached = self.client.get("/api/classroom/courses?auto_sync=true")
            manual = self.client.post("/api/classroom/sync")
        self.assertEqual(cached.status_code, 200)
        self.assertEqual(cached.json()["courses"][0]["id"], "cached-course")
        self.assertEqual(manual.status_code, 403)
        sync.assert_not_called()

    def test_expired_student_notification_read_does_not_create_reminders(self) -> None:
        launch_at = datetime.now(UTC) - timedelta(days=31)
        with Session(self.engine) as db:
            student = db.get(User, self.student_id)
            policy = db.get(LicensingPolicy, 1)
            assert student is not None
            assert policy is not None
            student.created_at = launch_at - timedelta(days=365)
            policy.launch_at = launch_at
            course = Course(
                user_id=self.student_id,
                google_course_id="due-course",
                course_name="Due course",
                is_active=True,
            )
            db.add(course)
            db.flush()
            db.add(
                Assignment(
                    user_id=self.student_id,
                    course_id=course.id,
                    google_assignment_id="due-assignment",
                    title="Due today",
                    due_date=datetime.now(UTC),
                    submission_status="not_started",
                    is_demo=False,
                )
            )
            db.add(
                License(
                    user_id=self.student_id,
                    plan_id=self.plan_id,
                    starts_at=datetime.now(UTC) - timedelta(days=400),
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
            db.commit()
        response = self.client.get("/api/notifications")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["notifications"], [])

    def test_admin_can_record_refund_and_revoke_current_license(self) -> None:
        submitted = self._submit()
        self.assertEqual(self._approve(submitted.json()["id"]).status_code, 200)
        self.current_user = self.admin
        response = self.client.post(
            f"/api/admin/payments/{submitted.json()['id']}/refund",
            json={"password": "AdminSecure123!", "reason": "Payment was returned."},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["current_license_revoked"])
        self.current_user = self.student
        status = self.client.get("/api/licenses/status")
        self.assertEqual(status.json()["status"], "revoked")

    def test_admin_can_configure_grandfathering_before_launch(self) -> None:
        self.current_user = self.admin
        launch_at = datetime.now(UTC) + timedelta(days=1)
        response = self.client.patch(
            "/api/admin/license-policy",
            json={
                "password": "AdminSecure123!",
                "launch_at": launch_at.isoformat(),
                "grandfathering_days": 30,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["grandfathering_days"], 30)
        self.assertFalse(response.json()["locked"])

    def test_grandfathering_is_time_bounded_and_only_for_existing_users(self) -> None:
        launch = datetime.now(UTC) - timedelta(days=1)
        with Session(self.engine) as db:
            policy = db.get(LicensingPolicy, 1)
            policy.launch_at = launch
            policy.grandfathering_days = 30
            existing = db.get(User, self.student_id)
            existing.created_at = launch - timedelta(days=30)
            new_user = User(
                full_name="New Student",
                email="new@example.test",
                hashed_password=hash_password("NewStudent123!"),
            )
            db.add(new_user)
            db.flush()
            self.assertTrue(get_license_status(db, existing).active)
            self.assertEqual(get_license_status(db, existing).source, "grandfathered")
            self.assertFalse(get_license_status(db, new_user).active)
            db.commit()

    def test_prelaunch_period_preserves_existing_access(self) -> None:
        with Session(self.engine) as db:
            policy = db.get(LicensingPolicy, 1)
            policy.launch_at = datetime.now(UTC) + timedelta(days=1)
            status = get_license_status(db, db.get(User, self.student_id))
            self.assertTrue(status.active)
            self.assertEqual(status.source, "prelaunch")


class CalendarMonthTests(unittest.TestCase):
    def test_month_end_is_preserved_and_clamped(self) -> None:
        self.assertEqual(
            add_calendar_months(datetime(2024, 8, 31, 12, tzinfo=UTC), 6),
            datetime(2025, 2, 28, 12, tzinfo=UTC),
        )
        self.assertEqual(
            add_calendar_months(datetime(2024, 2, 29, 12, tzinfo=UTC), 6),
            datetime(2024, 8, 31, 12, tzinfo=UTC),
        )
        self.assertEqual(
            add_calendar_months(datetime(2023, 1, 30, 12, tzinfo=UTC), 1),
            datetime(2023, 2, 28, 12, tzinfo=UTC),
        )
