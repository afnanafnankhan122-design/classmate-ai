from datetime import date, datetime, timezone, timedelta
import unittest
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_google_token, encrypt_google_token
from app.database.base import Base
from app.models.assignment import Assignment
from app.models.course import Course
from app.models.google_account import GoogleAccount
from app.models.user import User
from app.services.google_classroom import (
    _parse_google_deadline,
    classroom_assignment_dict,
    sync_classroom_data,
)
from app.services.google_oauth import get_classroom_credentials, save_google_login
from app.api.routes.dashboard import _is_due_today, _is_overdue


class GoogleClassroomSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fernet_key = Fernet.generate_key().decode("ascii")
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(full_name="Test Student", email="student@example.test")
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_sync_persists_assignments_and_upserts_duplicates(self) -> None:
        local_today = datetime.now(ZoneInfo("Asia/Karachi")).date()
        courses = [
            {
                "id": "course-1",
                "name": "Computer Science",
                "section": "Section A",
                "courseState": "ACTIVE",
                "alternateLink": "https://classroom.google.com/c/course-1",
                "timeZone": "Asia/Karachi",
            }
        ]
        coursework = [
            (
                "course-1",
                {
                    "id": "assignment-1",
                    "title": "Operating Systems Lab",
                    "description": "Complete the scheduling exercise.",
                    "alternateLink": "https://classroom.google.com/c/course-1/a/assignment-1",
                    "maxPoints": 100,
                    "dueDate": {
                        "year": local_today.year,
                        "month": local_today.month,
                        "day": local_today.day,
                    },
                    "dueTime": {"hours": 18, "minutes": 30},  # 23:30 PKT (18:30 UTC) is due today in Pakistan
                    "materials": [
                        {
                            "driveFile": {
                                "driveFile": {
                                    "id": "drive-file-1",
                                    "title": "Lab brief",
                                    "alternateLink": "https://drive.google.com/file/d/drive-file-1",
                                }
                            }
                        },
                        {
                            "link": {
                                "url": "https://aust.edu.pk/resources",
                                "title": "AUST Resource Portal",
                            }
                        },
                        {
                            "form": {
                                "formUrl": "https://forms.google.com/quiz-1",
                                "title": "Quiz Submission Form",
                            }
                        },
                    ],
                },
            )
        ]
        submission_states = {
            "assignment-1": "turned_in"
        }

        # Add GoogleAccount to check last_synced_at
        account = GoogleAccount(
            user_id=self.user.id,
            google_sub="sub-123",
            google_email="student@example.test",
        )
        self.db.add(account)
        self.db.commit()

        with patch(
            "app.services.google_classroom._fetch_classroom_data",
            return_value=(courses, coursework, submission_states),
        ):
            first_sync = sync_classroom_data(self.db, self.user.id, credentials=None)
            second_sync = sync_classroom_data(self.db, self.user.id, credentials=None)

        self.assertEqual(first_sync["new_courses"], 1)
        self.assertEqual(first_sync["new_assignments"], 1)
        self.assertEqual(second_sync["new_courses"], 0)
        self.assertEqual(second_sync["new_assignments"], 0)

        assignment = self.db.scalar(select(Assignment))
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.description, "Complete the scheduling exercise.")
        self.assertEqual(assignment.alternate_link, "https://classroom.google.com/c/course-1/a/assignment-1")
        self.assertEqual(assignment.max_points, 100)
        self.assertEqual(len(assignment.attachments), 3)
        self.assertEqual(assignment.attachments[0]["title"], "Lab brief")
        self.assertEqual(assignment.attachments[1]["url"], "https://aust.edu.pk/resources")
        self.assertEqual(assignment.attachments[2]["url"], "https://forms.google.com/quiz-1")
        self.assertFalse(assignment.is_demo)
        self.assertEqual(assignment.submission_status, "turned_in")

        assignment.course = self.db.scalar(select(Course))
        self.assertEqual(assignment.course.course_state, "ACTIVE")
        self.assertEqual(assignment.course.alternate_link, "https://classroom.google.com/c/course-1")
        self.assertTrue(classroom_assignment_dict(assignment)["due_today"])

        # Check last_synced_at
        self.db.refresh(account)
        self.assertIsNotNone(account.last_synced_at)

    def test_no_due_date_is_not_classified_due_today(self) -> None:
        course = Course(
            user_id=self.user.id,
            google_course_id="course-no-due-date",
            course_name="No deadline course",
            time_zone="Asia/Karachi",
        )
        assignment = Assignment(
            user_id=self.user.id,
            course=course,
            google_assignment_id="assignment-no-due-date",
            title="Reading",
            attachments=[],
            is_demo=False,
        )
        self.assertFalse(classroom_assignment_dict(assignment)["due_today"])
        self.assertIsNone(classroom_assignment_dict(assignment)["due_date"])

    def test_empty_sync_deactivates_previous_classrooms(self) -> None:
        course = Course(
            user_id=self.user.id,
            google_course_id="course-previous",
            course_name="Previous classroom",
        )
        self.db.add(course)
        self.db.commit()

        with patch(
            "app.services.google_classroom._fetch_classroom_data",
            return_value=([], [], {}),
        ):
            result = sync_classroom_data(self.db, self.user.id, credentials=None)

        self.assertEqual(result["course_count"], 0)
        self.assertFalse(self.db.scalar(select(Course)).is_active)

    def test_token_refresh_when_expired(self) -> None:
        with patch.object(settings, "google_token_encryption_key", self.fernet_key):
            with patch.object(settings, "google_client_id", "test-client-id"):
                with patch.object(settings, "google_client_secret", "test-client-secret"):
                    account = GoogleAccount(
                        user_id=self.user.id,
                        google_sub="google-user-expired",
                        google_email="student@aust.edu.pk",
                        encrypted_access_token=encrypt_google_token("expired-access-token"),
                        encrypted_refresh_token=encrypt_google_token("valid-refresh-token"),
                        token_expiry=datetime.now(timezone.utc) - timedelta(hours=2),
                    )
                    self.db.add(account)
                    self.db.commit()

                    # Mock refresh call on Google Credentials
                    def mock_refresh_behavior(request):
                        mock_creds.token = "refreshed-access-token-new"
                        mock_creds.expiry = datetime.now(timezone.utc) + timedelta(hours=1)

                    with patch("app.services.google_oauth.Credentials") as MockCredsClass:
                        mock_creds = MagicMock()
                        mock_creds.token = "expired-access-token"
                        mock_creds.refresh_token = "valid-refresh-token"
                        mock_creds.expired = True
                        mock_creds.valid = False
                        mock_creds.expiry = datetime.now(timezone.utc) - timedelta(hours=2)
                        mock_creds.refresh = MagicMock(side_effect=mock_refresh_behavior)
                        MockCredsClass.return_value = mock_creds

                        creds = get_classroom_credentials(self.db, account)

                        # Check that refresh was called
                        mock_creds.refresh.assert_called_once()
                        # Check that DB was updated with new encrypted token
                        self.db.refresh(account)
                        decrypted_new_token = decrypt_google_token(account.encrypted_access_token)
                        self.assertEqual(decrypted_new_token, "refreshed-access-token-new")

    def test_timezone_due_at_10_am_pakistan_time(self) -> None:
        # Teacher in PKT sets deadline at 10:00 AM Pakistan time
        # Google Classroom API returns 05:00 UTC (10:00 PKT - 5 hours)
        coursework = {
            "dueDate": {"year": 2026, "month": 11, "day": 4},
            "dueTime": {"hours": 5, "minutes": 0},
        }
        due_utc, due_time_str = _parse_google_deadline(coursework, "Asia/Karachi")
        self.assertIsNotNone(due_utc)
        self.assertEqual(due_time_str, "10:00 AM")
        # In UTC datetime
        self.assertEqual(due_utc, datetime(2026, 11, 4, 5, 0, 0))
        # When converted to Asia/Karachi
        due_pkt = due_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Karachi"))
        self.assertEqual(due_pkt.hour, 10)
        self.assertEqual(due_pkt.minute, 0)
        self.assertEqual(due_pkt.strftime("%I:%M %p"), "10:00 AM")

    def test_timezone_due_at_11_59_pm_pakistan_time(self) -> None:
        # Teacher in PKT sets deadline at 11:59 PM Pakistan time
        # Google Classroom API returns 18:59 UTC (23:59 PKT - 5 hours)
        coursework = {
            "dueDate": {"year": 2026, "month": 11, "day": 4},
            "dueTime": {"hours": 18, "minutes": 59},
        }
        due_utc, due_time_str = _parse_google_deadline(coursework, "Asia/Karachi")
        self.assertIsNotNone(due_utc)
        self.assertEqual(due_time_str, "11:59 PM")
        self.assertEqual(due_utc, datetime(2026, 11, 4, 18, 59, 0))
        # When converted to Asia/Karachi
        due_pkt = due_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Karachi"))
        self.assertEqual(due_pkt.hour, 23)
        self.assertEqual(due_pkt.minute, 59)
        self.assertEqual(due_pkt.strftime("%I:%M %p"), "11:59 PM")

    def test_timezone_assignment_with_date_but_no_due_time(self) -> None:
        # Date-only deadline: e.g. 2026-11-04 with no dueTime specified
        # Must not shift calendar day when converted to/from UTC
        coursework = {
            "dueDate": {"year": 2026, "month": 11, "day": 4},
        }
        due_utc, due_time_str = _parse_google_deadline(coursework, "Asia/Karachi")
        self.assertIsNotNone(due_utc)
        self.assertIsNone(due_time_str)
        # In Asia/Karachi, must still be on 2026-11-04
        due_pkt = due_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Karachi"))
        self.assertEqual(due_pkt.date(), date(2026, 11, 4))
        self.assertEqual(due_pkt.hour, 23)
        self.assertEqual(due_pkt.minute, 59)
        self.assertEqual(due_pkt.second, 59)

    def test_timezone_assignment_due_tomorrow_in_pakistan(self) -> None:
        pkt_now = datetime.now(ZoneInfo("Asia/Karachi"))
        pkt_tomorrow = pkt_now.date() + timedelta(days=1)
        # Assignment due tomorrow at 11:59 PM PKT (18:59 UTC)
        coursework = {
            "dueDate": {"year": pkt_tomorrow.year, "month": pkt_tomorrow.month, "day": pkt_tomorrow.day},
            "dueTime": {"hours": 18, "minutes": 59},
        }
        due_utc, due_time_str = _parse_google_deadline(coursework, "Asia/Karachi")
        course = Course(
            user_id=self.user.id,
            google_course_id="course-tomorrow",
            course_name="Tomorrow Course",
            time_zone="Asia/Karachi",
        )
        assignment = Assignment(
            user_id=self.user.id,
            course=course,
            google_assignment_id="asgn-tomorrow",
            title="Tomorrow Assignment",
            due_date=due_utc,
            due_time=due_time_str,
            submission_status="assigned",
            is_demo=False,
        )
        # Should NOT be due today
        self.assertFalse(_is_due_today(assignment, ZoneInfo("Asia/Karachi")))
        # Should NOT be overdue
        now_utc = datetime.now(timezone.utc)
        self.assertFalse(_is_overdue(assignment, now_utc))

    def test_timezone_assignment_already_overdue_in_pakistan(self) -> None:
        pkt_now = datetime.now(ZoneInfo("Asia/Karachi"))
        pkt_yesterday = pkt_now.date() - timedelta(days=1)
        # Assignment due yesterday at 11:59 PM PKT (18:59 UTC)
        coursework = {
            "dueDate": {"year": pkt_yesterday.year, "month": pkt_yesterday.month, "day": pkt_yesterday.day},
            "dueTime": {"hours": 18, "minutes": 59},
        }
        due_utc, due_time_str = _parse_google_deadline(coursework, "Asia/Karachi")
        course = Course(
            user_id=self.user.id,
            google_course_id="course-overdue",
            course_name="Overdue Course",
            time_zone="Asia/Karachi",
        )
        assignment = Assignment(
            user_id=self.user.id,
            course=course,
            google_assignment_id="asgn-overdue",
            title="Overdue Assignment",
            due_date=due_utc,
            due_time=due_time_str,
            submission_status="assigned",
            is_demo=False,
        )
        # Should NOT be due today
        self.assertFalse(_is_due_today(assignment, ZoneInfo("Asia/Karachi")))
        # MUST be overdue
        now_utc = datetime.now(timezone.utc)
        self.assertTrue(_is_overdue(assignment, now_utc))

    def test_google_link_rejects_an_identity_that_does_not_match_the_student(self) -> None:
        profile = {
            "id": "google-sub",
            "email": "someone-else@example.test",
            "verified_email": True,
            "name": "Someone Else",
        }

        with self.assertRaisesRegex(ValueError, "must match the registered"):
            save_google_login(
                self.db,
                self.user,
                profile,
                Credentials(token="temporary-access-token"),
            )

        self.assertEqual(self.db.query(User).count(), 1)
        self.assertEqual(self.db.query(GoogleAccount).count(), 0)

    def test_google_link_verifies_a_matching_provider_email(self) -> None:
        profile = {
            "id": "google-sub",
            "email": self.user.email,
            "verified_email": True,
            "name": self.user.full_name,
        }

        with patch.object(settings, "google_token_encryption_key", self.fernet_key):
            linked_user = save_google_login(
                self.db,
                self.user,
                profile,
                Credentials(token="temporary-access-token"),
            )

        self.assertTrue(linked_user.is_verified)
        self.assertEqual(self.db.query(GoogleAccount).count(), 1)


if __name__ == "__main__":
    unittest.main()
