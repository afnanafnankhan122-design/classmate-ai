from datetime import date, datetime, time, timezone, UTC
import logging
from typing import Any, Callable
from zoneinfo import ZoneInfo

from google.auth.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.assignment import Assignment
from app.models.course import Course
from app.models.google_account import GoogleAccount
from app.services.google_oauth import is_google_insufficient_permissions

logger = logging.getLogger(__name__)


def _pages(list_request: Callable[[str | None], Any], item_key: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        response = list_request(page_token).execute()
        items.extend(response.get(item_key, []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return items


def _time_zone(course_data: dict[str, Any]) -> ZoneInfo:
    zone_name = course_data.get("timeZone") or settings.app_timezone
    try:
        return ZoneInfo(zone_name)
    except Exception:
        return ZoneInfo("Asia/Karachi")


def _parse_google_deadline(
    coursework: dict[str, Any],
    tz_name: str | None = None,
) -> tuple[datetime | None, str | None]:
    """Parse Google Classroom dueDate and dueTime.

    Google Classroom API documentation specifies:
    - dueDate is an object (Date) in UTC.
    - dueTime is an object (TimeOfDay) in UTC.

    When both are present, they define an exact UTC instant.
    When dueDate is present but dueTime is omitted, this is a date-only deadline.
    It must not be interpreted as a UTC timestamp that shifts days.
    Instead, it expires at 23:59:59 at the end of the due day in the course timezone (Asia/Karachi),
    and due_time is set to None.
    """
    due = coursework.get("dueDate")
    if not due:
        return None, None

    year = int(due.get("year", 0))
    month = int(due.get("month", 0))
    day = int(due.get("day", 0))
    if not (year and month and day):
        return None, None

    due_day = date(year, month, day)
    time_data = coursework.get("dueTime")

    try:
        app_tz = ZoneInfo(tz_name or settings.app_timezone)
    except Exception:
        app_tz = ZoneInfo("Asia/Karachi")

    if isinstance(time_data, dict) and "hours" in time_data:
        h = int(time_data.get("hours", 0))
        m = int(time_data.get("minutes", 0))
        s = int(time_data.get("seconds", 0))
        # Both dueDate and dueTime from Google API are in UTC
        due_utc = datetime.combine(due_day, time(h, m, s), tzinfo=timezone.utc)
        due_local = due_utc.astimezone(app_tz)
        due_time_str = due_local.strftime("%I:%M %p")
        return due_utc.replace(tzinfo=None), due_time_str
    else:
        # Date-only deadline: expires at 23:59:59 at the end of the day in local timezone
        due_local = datetime.combine(due_day, time(23, 59, 59), tzinfo=app_tz)
        due_utc = due_local.astimezone(timezone.utc)
        return due_utc.replace(tzinfo=None), None


def _due_at(
    coursework: dict[str, Any],
    course_data: dict[str, Any],
) -> datetime | None:
    due_dt, _ = _parse_google_deadline(coursework, course_data.get("timeZone"))
    return due_dt


def _attachments(coursework: dict[str, Any]) -> list[dict[str, str]]:
    attachments: list[dict[str, str]] = []
    for material in coursework.get("materials", []):
        for material_type in ("driveFile", "link", "youtubeVideo", "form"):
            item = material.get(material_type)
            if not isinstance(item, dict):
                continue
            drive_file = item.get("driveFile", item)
            attachment: dict[str, str] = {"type": material_type}
            for key, value in (
                ("id", drive_file.get("id")),
                ("title", drive_file.get("title")),
                ("url", drive_file.get("alternateLink") or drive_file.get("url") or drive_file.get("formUrl")),
                ("thumbnail_url", drive_file.get("thumbnailUrl")),
            ):
                if isinstance(value, str) and value:
                    attachment[key] = value
            attachments.append(attachment)
    return attachments


def _map_submission_state(raw_state: str | None) -> str:
    if not raw_state:
        return "not_started"
    state = raw_state.upper()
    if state == "TURNED_IN":
        return "turned_in"
    if state == "RETURNED":
        return "graded"
    if state in ("NEW", "CREATED"):
        return "assigned"
    if state == "RECLAIMED_BY_STUDENT":
        return "unsubmitted"
    return state.lower()


def _fetch_classroom_data(
    credentials: Credentials,
) -> tuple[list[dict[str, Any]], list[tuple[str, dict[str, Any]]], dict[str, str]]:
    classroom = build("classroom", "v1", credentials=credentials, cache_discovery=False)

    courses_by_id: dict[str, dict[str, Any]] = {}
    api_success = False
    last_http_error: HttpError | None = None

    # This application syncs the requesting student's own courses only.
    try:
        student_courses = _pages(
            lambda page_token: classroom.courses().list(
                studentId="me",
                courseStates=["ACTIVE"],
                pageSize=100,
                **({"pageToken": page_token} if page_token else {}),
            ),
            "courses",
        )
        api_success = True
        for c in student_courses:
            if c.get("id"):
                courses_by_id[c["id"]] = c
    except HttpError as exc:
        last_http_error = exc
        logger.warning("Error fetching student courses: %s", exc)

    # If NO API call succeeded and an HttpError was raised, raise it!
    # This prevents falsely claiming sync succeeded when API was disabled or unauthorized.
    if not api_success and last_http_error is not None:
        raise last_http_error

    courses = list(courses_by_id.values())
    coursework_by_course: list[tuple[str, dict[str, Any]]] = []
    submission_states: dict[str, str] = {}

    for course in courses:
        course_id = course.get("id")
        if not isinstance(course_id, str) or not course_id:
            continue

        try:
            assignments = _pages(
                lambda page_token: classroom.courses()
                .courseWork()
                .list(
                    courseId=course_id,
                    pageSize=100,
                    orderBy="dueDate asc",
                    **({"pageToken": page_token} if page_token else {}),
                ),
                "courseWork",
            )
            coursework_by_course.extend((course_id, assignment) for assignment in assignments)
        except HttpError as exc:
            if is_google_insufficient_permissions(exc):
                raise
            logger.warning("Error fetching coursework for course %s: %s", course_id, exc)
            continue

        # Try to retrieve student submissions for this course
        try:
            submissions = _pages(
                lambda page_token: classroom.courses()
                .courseWork()
                .studentSubmissions()
                .list(
                    courseId=course_id,
                    courseWorkId="-",
                    userId="me",
                    pageSize=100,
                    **({"pageToken": page_token} if page_token else {}),
                ),
                "studentSubmissions",
            )
            for sub in submissions:
                cw_id = sub.get("courseWorkId")
                if cw_id:
                    submission_states[cw_id] = _map_submission_state(sub.get("state"))
        except HttpError as exc:
            if is_google_insufficient_permissions(exc):
                raise
            logger.warning("Error fetching submissions for course %s: %s", course_id, exc)

    return courses, coursework_by_course, submission_states


def sync_classroom_data(
    db: Session,
    user_id: int,
    credentials: Credentials,
) -> dict[str, Any]:
    google_courses, coursework_items, submission_states = _fetch_classroom_data(credentials)
    local_courses: dict[str, Course] = {}
    created_courses = 0
    created_assignments = 0

    # Mark existing courses inactive prior to reconciling
    db.execute(
        update(Course)
        .where(Course.user_id == user_id)
        .values(is_active=False)
    )

    for course_data in google_courses:
        google_course_id = course_data.get("id")
        if not isinstance(google_course_id, str) or not google_course_id:
            continue
        course_time_zone = course_data.get("timeZone") or settings.app_timezone
        _time_zone({"timeZone": course_time_zone})

        course = db.scalar(
            select(Course).where(
                Course.user_id == user_id,
                Course.google_course_id == google_course_id,
            )
        )
        if course is None:
            course = Course(
                user_id=user_id,
                google_course_id=google_course_id,
                course_name=course_data.get("name") or "Untitled classroom",
            )
            db.add(course)
            db.flush()
            created_courses += 1

        course.course_name = course_data.get("name") or "Untitled classroom"
        course.course_section = course_data.get("section")
        course.course_state = course_data.get("courseState") or "ACTIVE"
        course.alternate_link = course_data.get("alternateLink")
        course.time_zone = course_time_zone
        course.is_active = True
        local_courses[google_course_id] = course

    for google_course_id, coursework in coursework_items:
        course = local_courses.get(google_course_id)
        google_assignment_id = coursework.get("id")
        if course is None or not isinstance(google_assignment_id, str):
            continue

        assignment = db.scalar(
            select(Assignment).where(
                Assignment.course_id == course.id,
                Assignment.google_assignment_id == google_assignment_id,
            )
        )
        if assignment is None:
            assignment = Assignment(
                user_id=user_id,
                course_id=course.id,
                google_assignment_id=google_assignment_id,
                title=coursework.get("title") or "Untitled assignment",
            )
            db.add(assignment)
            created_assignments += 1

        assignment.title = coursework.get("title") or "Untitled assignment"
        assignment.description = coursework.get("description")
        assignment.alternate_link = coursework.get("alternateLink")
        assignment.max_points = coursework.get("maxPoints")
        due_date, due_time_str = _parse_google_deadline(
            coursework,
            course.time_zone or settings.app_timezone,
        )
        assignment.due_date = due_date
        assignment.due_time = due_time_str
        assignment.attachments = _attachments(coursework)
        assignment.status = "classroom"
        assignment.submission_status = submission_states.get(
            google_assignment_id, "assigned"
        )
        assignment.is_demo = False

    # Update last_synced_at timestamp on GoogleAccount
    now_utc = datetime.now(UTC)
    account = db.scalar(select(GoogleAccount).where(GoogleAccount.user_id == user_id))
    if account is not None:
        account.last_synced_at = now_utc

    db.commit()

    return {
        "course_count": len(local_courses),
        "assignment_count": len(coursework_items),
        "new_courses": created_courses,
        "new_assignments": created_assignments,
        "last_synced_at": now_utc.isoformat(),
    }


def classroom_assignment_dict(assignment: Assignment) -> dict[str, Any]:
    course = assignment.course
    app_tz = ZoneInfo(settings.app_timezone)
    course_tz = ZoneInfo(course.time_zone) if (course and course.time_zone) else app_tz
    due_at = assignment.due_date
    if due_at is not None:
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        local_due = due_at.astimezone(course_tz)
        now_local = datetime.now(course_tz)
        due_today = local_due.date() == now_local.date()
        due_date = local_due.isoformat()
        if assignment.due_time:
            time_display = (
                assignment.due_time
                if ("AM" in assignment.due_time or "PM" in assignment.due_time)
                else local_due.strftime("%I:%M %p")
            )
            deadline = f"{local_due.strftime('%b %d')}, {time_display} PKT"
        else:
            deadline = f"{local_due.strftime('%b %d, %Y')} (No due time) PKT"
    else:
        due_today = False
        due_date = None
        deadline = "No due date specified"

    return {
        "id": assignment.id,
        "google_assignment_id": assignment.google_assignment_id,
        "title": assignment.title,
        "description": assignment.description,
        "due_date": due_date,
        "due_time": assignment.due_time,
        "due_today": due_today,
        "deadline": deadline,
        "time_zone": course.time_zone if (course and course.time_zone) else settings.app_timezone,
        "course_id": course.google_course_id if course else None,
        "course_name": course.course_name if course else "Classroom",
        "course_section": course.course_section if course else None,
        "course_state": course.course_state if course else "ACTIVE",
        "alternate_link": assignment.alternate_link,
        "max_points": assignment.max_points,
        "attachments": assignment.attachments or [],
        "submission_status": assignment.submission_status,
        "processing_status": assignment.processing_status,
        "source": "google_classroom",
    }
