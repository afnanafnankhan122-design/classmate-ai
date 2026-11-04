"""Comprehensive tests for Student Authentication, Registration, Password Recovery, Profiles, and Multi-Student Isolation."""

from datetime import datetime, UTC, timedelta
import unittest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.auth_security import hash_password, hash_token, validate_password_strength, verify_password
from app.database.base import Base
from app.models.assignment import Assignment
from app.models.course import Course
from app.models.google_account import GoogleAccount
from app.models.notification import Notification
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User


class StudentAuthUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_password_hashing_and_verification(self) -> None:
        raw = "StudentSecurePass123!"
        hashed = hash_password(raw)
        self.assertNotEqual(raw, hashed)
        self.assertTrue(verify_password(raw, hashed))
        self.assertFalse(verify_password("WrongPass123!", hashed))
        self.assertFalse(verify_password("", hashed))
        self.assertFalse(verify_password(raw, None))

    def test_password_strength_validation(self) -> None:
        valid, msg = validate_password_strength("Short1!")
        self.assertFalse(valid)
        self.assertIn("at least 8", msg)

        valid, msg = validate_password_strength("alllowercase123!")
        self.assertFalse(valid)
        self.assertIn("uppercase", msg)

        valid, msg = validate_password_strength("ALLUPPERCASE123!")
        self.assertFalse(valid)
        self.assertIn("lowercase", msg)

        valid, msg = validate_password_strength("NoDigitsOrSpecial")
        self.assertFalse(valid)
        self.assertIn("digit or special", msg)

        valid, msg = validate_password_strength("StrongPass2026!")
        self.assertTrue(valid)
        self.assertEqual(msg, "")

    def test_student_registration_and_persistence(self) -> None:
        hashed = hash_password("MyClassroomPass2026!")
        user = User(
            full_name="Afnan Khan",
            email="afnan.student@aust.edu.pk",
            hashed_password=hashed,
            department="Software Engineering",
            semester="6th",
            roll_number="BSSE-2101",
        )
        self.db.add(user)
        self.db.commit()

        retrieved = self.db.scalar(select(User).where(User.email == "afnan.student@aust.edu.pk"))
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.full_name, "Afnan Khan")
        self.assertTrue(verify_password("MyClassroomPass2026!", retrieved.hashed_password))

    def test_password_reset_token_lifecycle(self) -> None:
        user = User(
            full_name="Testing Student",
            email="reset.student@aust.edu.pk",
            hashed_password=hash_password("OldPassword123!"),
        )
        self.db.add(user)
        self.db.commit()

        raw_token = "secure-random-token-xyz-12345"
        token_hash = hash_token(raw_token)
        expires = datetime.now(UTC) + timedelta(minutes=15)

        reset_record = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires,
        )
        self.db.add(reset_record)
        self.db.commit()

        # Check lookup by token hash
        found = self.db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > datetime.now(UTC),
            )
        )
        self.assertIsNotNone(found)
        self.assertEqual(found.user.email, "reset.student@aust.edu.pk")

        # Mark as used and update password
        found.user.hashed_password = hash_password("NewSecurePassword456!")
        found.used_at = datetime.now(UTC)
        self.db.commit()

        # Token cannot be reused
        reused = self.db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
            )
        )
        self.assertIsNone(reused)

        # Verify new password works and old password fails
        self.db.refresh(user)
        self.assertTrue(verify_password("NewSecurePassword456!", user.hashed_password))
        self.assertFalse(verify_password("OldPassword123!", user.hashed_password))

    def test_multi_student_data_isolation(self) -> None:
        # Create Student A
        student_a = User(
            full_name="Student Alpha",
            email="alpha@aust.edu.pk",
            hashed_password=hash_password("PassAlpha123!"),
        )
        # Create Student B
        student_b = User(
            full_name="Student Beta",
            email="beta@aust.edu.pk",
            hashed_password=hash_password("PassBeta123!"),
        )
        self.db.add_all([student_a, student_b])
        self.db.commit()

        # Assign course and assignment to Student A
        course_a = Course(
            user_id=student_a.id,
            google_course_id="c-alpha-1",
            course_name="Compiler Construction",
            time_zone="Asia/Karachi",
        )
        self.db.add(course_a)
        self.db.flush()

        asgn_a = Assignment(
            user_id=student_a.id,
            course_id=course_a.id,
            google_assignment_id="a-alpha-1",
            title="Lexical Analyzer Lab",
            is_demo=False,
        )
        # Notification for Student A
        notif_a = Notification(
            user_id=student_a.id,
            title="Assignment Due",
            message="Compiler lab is due tomorrow.",
            is_read=False,
        )
        # Notification for Student B
        notif_b = Notification(
            user_id=student_b.id,
            title="Welcome Beta",
            message="Welcome to ClassMate AI.",
            is_read=False,
        )
        self.db.add_all([asgn_a, notif_a, notif_b])
        self.db.commit()

        # Verify Student B queries ONLY return Student B's data
        b_assignments = self.db.scalars(
            select(Assignment).where(Assignment.user_id == student_b.id)
        ).all()
        self.assertEqual(len(b_assignments), 0)

        b_notifications = self.db.scalars(
            select(Notification).where(Notification.user_id == student_b.id)
        ).all()
        self.assertEqual(len(b_notifications), 1)
        self.assertEqual(b_notifications[0].title, "Welcome Beta")

        # Verify Student A queries ONLY return Student A's data
        a_assignments = self.db.scalars(
            select(Assignment).where(Assignment.user_id == student_a.id)
        ).all()
        self.assertEqual(len(a_assignments), 1)
        self.assertEqual(a_assignments[0].title, "Lexical Analyzer Lab")


if __name__ == "__main__":
    unittest.main()

