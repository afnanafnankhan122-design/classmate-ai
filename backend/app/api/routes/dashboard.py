from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.database.dependencies import get_db
from app.models.approval import Approval
from app.models.assignment import Assignment
from app.models.course import Course
from app.models.user import User
from app.services.google_classroom import classroom_assignment_dict
from app.services.google_oauth import get_user_google_account

router = APIRouter()

DEMO_DATA = {
    "is_demo": True,
    "authenticated": False,
    "google_connected": False,
    "stats": [
        {"label": "Total Assignments", "value": "38", "delta": "+4 this week", "tone": "blue"},
        {"label": "Pending Assignments", "value": "12", "delta": "2 due today", "tone": "cyan"},
        {"label": "Due Today", "value": "4", "delta": "Needs urgent review", "tone": "amber"},
        {"label": "Overdue", "value": "3", "delta": "1 critical", "tone": "rose"},
        {"label": "Completed", "value": "18", "delta": "+6% completion", "tone": "green"},
        {"label": "Awaiting Approval", "value": "7", "delta": "3 PDFs ready", "tone": "violet"},
    ],
    "assignments": [
        {
            "id": 1,
            "title": "Operating Systems Lab 04",
            "course": "CS-204 Operating Systems",
            "teacher": "Dr. Sajid Khan",
            "deadline": "Today, 11:59 PM",
            "status": "In Progress",
            "ai": "Ready for review",
            "submission": "Draft",
            "alternate_link": None,
        },
        {
            "id": 2,
            "title": "Database Normalization Quiz",
            "course": "CS-310 Database Systems",
            "teacher": "Ms. Ayesha Qureshi",
            "deadline": "Tomorrow, 5:00 PM",
            "status": "Scheduled",
            "ai": "Analyzing instructions",
            "submission": "Not started",
            "alternate_link": None,
        },
        {
            "id": 3,
            "title": "Web Fundamentals Project",
            "course": "SE-205 Web Engineering",
            "teacher": "Mr. Usman Ali",
            "deadline": "Wed, 9:00 AM",
            "status": "Needs Review",
            "ai": "Completed",
            "submission": "Awaiting approval",
            "alternate_link": None,
        },
        {
            "id": 4,
            "title": "Computer Networks Case Study",
            "course": "CS-306 Networks",
            "teacher": "Dr. Hina Riaz",
            "deadline": "Thu, 2:30 PM",
            "status": "Scheduled",
            "ai": "Processing",
            "submission": "Not started",
            "alternate_link": None,
        },
    ],
    "recentActivity": [
        {"text": "AI solution generated", "time": "2 hours ago"},
        {"text": "PDF passed quality review", "time": "5 hours ago"},
        {"text": "Google Classroom sync completed", "time": "Yesterday"},
    ],
    "upcomingDeadlines": [
        {"title": "Network Security Report", "date": "3 days"},
        {"title": "Algorithms Lab Test", "date": "5 days"},
        {"title": "Software Design Memo", "date": "1 week"},
    ],
    "chartData": [
        {"day": "Mon", "value": 28},
        {"day": "Tue", "value": 35},
        {"day": "Wed", "value": 31},
        {"day": "Thu", "value": 44},
        {"day": "Fri", "value": 52},
        {"day": "Sat", "value": 46},
        {"day": "Sun", "value": 59},
    ],
}


def _is_submitted(a: Assignment) -> bool:
    return (a.submission_status or "").lower() in ("turned_in", "graded")


def _is_due_today(a: Assignment, app_tz: ZoneInfo) -> bool:
    if a.due_date is None:
        return False
    tz = ZoneInfo(a.course.time_zone) if (a.course and a.course.time_zone) else app_tz
    due_dt = a.due_date if a.due_date.tzinfo else a.due_date.replace(tzinfo=timezone.utc)
    return due_dt.astimezone(tz).date() == datetime.now(tz).date()


def _is_overdue(a: Assignment, now_utc: datetime) -> bool:
    if a.due_date is None:
        return False
    due_utc = a.due_date if a.due_date.tzinfo else a.due_date.replace(tzinfo=timezone.utc)
    return due_utc < now_utc and not _is_submitted(a)


def _compute_dashboard_data(user: User, db: Session) -> dict:
    account = get_user_google_account(db, user.id)
    courses = db.scalars(
        select(Course)
        .where(Course.user_id == user.id, Course.is_active.is_(True))
        .order_by(Course.course_name)
    ).all()

    assignments = db.scalars(
        select(Assignment)
        .options(selectinload(Assignment.course))
        .join(Course, Assignment.course_id == Course.id)
        .where(
            Assignment.user_id == user.id,
            Assignment.is_demo.is_(False),
            Assignment.google_assignment_id.is_not(None),
            Course.is_active.is_(True),
        )
        .order_by(Assignment.due_date.asc().nulls_last(), Assignment.title)
    ).all()

    now_utc = datetime.now(timezone.utc)
    app_tz = ZoneInfo(settings.app_timezone)

    total_count = len(assignments)
    course_count = len(courses)

    completed_assignments = [a for a in assignments if _is_submitted(a)]
    pending_assignments = [a for a in assignments if not _is_submitted(a)]
    completed_count = len(completed_assignments)
    pending_count = len(pending_assignments)

    # Due today calculations
    due_today_all = [a for a in assignments if _is_due_today(a, app_tz)]
    due_today_outstanding = [a for a in pending_assignments if _is_due_today(a, app_tz)]
    due_today_completed = [a for a in completed_assignments if _is_due_today(a, app_tz)]

    due_today_count = len(due_today_outstanding)
    due_today_total = len(due_today_all)

    # Overdue calculations (deadlines passed and still not submitted)
    overdue_assignments = [a for a in assignments if _is_overdue(a, now_utc)]
    overdue_count = len(overdue_assignments)

    # Awaiting approval: genuine pending reviews from approvals table
    awaiting_approval_count = db.scalar(
        select(func.count(Approval.id))
        .join(Assignment, Approval.assignment_id == Assignment.id)
        .where(
            Assignment.user_id == user.id,
            Approval.approval_status.in_(["pending", "awaiting_approval"]),
        )
    ) or 0

    stats = [
        {
            "label": "Total Assignments",
            "value": str(total_count),
            "delta": f"{course_count} active classes",
            "tone": "blue",
        },
        {
            "label": "Pending Assignments",
            "value": str(pending_count),
            "delta": (
                f"{due_today_count} due today"
                if due_today_count > 0
                else ("All caught up" if pending_count == 0 else f"{overdue_count} overdue" if overdue_count > 0 else "On schedule")
            ),
            "tone": "cyan",
        },
        {
            "label": "Due Today",
            "value": str(due_today_count),
            "delta": (
                "Needs urgent review"
                if due_today_count > 0
                else (
                    "1 completed today"
                    if len(due_today_completed) == 1
                    else f"{len(due_today_completed)} completed today"
                    if len(due_today_completed) > 1
                    else "All caught up today"
                )
            ),
            "tone": "amber",
        },
        {
            "label": "Overdue",
            "value": str(overdue_count),
            "delta": f"{overdue_count} critical" if overdue_count > 0 else "None overdue",
            "tone": "rose",
        },
        {
            "label": "Completed",
            "value": str(completed_count),
            "delta": (
                f"{int(completed_count / total_count * 100)}% completion"
                if total_count > 0
                else "0% completion"
            ),
            "tone": "green",
        },
        {
            "label": "Awaiting Approval",
            "value": str(awaiting_approval_count),
            "delta": (
                f"{awaiting_approval_count} pending review"
                if awaiting_approval_count > 0
                else "None pending"
            ),
            "tone": "violet",
        },
    ]

    # Real assignment rows
    rows = []
    for a in assignments:
        d = classroom_assignment_dict(a)
        sub_status = (a.submission_status or "assigned").lower()
        if sub_status in ("turned_in", "graded"):
            status_label = "Turned In" if sub_status == "turned_in" else "Graded"
        elif _is_due_today(a, app_tz) and not _is_submitted(a):
            status_label = "Due Today"
        elif _is_overdue(a, now_utc):
            status_label = "Overdue"
        else:
            status_label = "In Progress"

        if d["due_date"]:
            try:
                local_dt = datetime.fromisoformat(d["due_date"])
                has_time = bool(a.due_time)
                if has_time:
                    time_str = (
                        a.due_time
                        if ("AM" in a.due_time or "PM" in a.due_time)
                        else local_dt.strftime("%I:%M %p")
                    )
                    if d["due_today"]:
                        deadline_str = f"Today, {time_str} PKT"
                    else:
                        deadline_str = f"{local_dt.strftime('%b %d')}, {time_str} PKT"
                else:
                    if d["due_today"]:
                        deadline_str = "Today (No due time) PKT"
                    else:
                        deadline_str = f"{local_dt.strftime('%b %d, %Y')} (No due time) PKT"
            except Exception:
                deadline_str = d["due_date"]
        else:
            deadline_str = "No deadline"

        submission_display = (
            "Turned In"
            if sub_status == "turned_in"
            else "Graded"
            if sub_status == "graded"
            else a.submission_status.replace("_", " ").title()
            if a.submission_status
            else "Assigned"
        )

        rows.append({
            "id": a.id,
            "title": a.title,
            "course": a.course.course_name if a.course else "Classroom",
            "teacher": a.course.course_section or "Google Classroom",
            "deadline": deadline_str,
            "status": status_label,
            "ai": "Ready for AI review",
            "submission": submission_display,
            "alternate_link": a.alternate_link,
            "max_points": a.max_points,
        })

    # Real upcoming deadlines (unsubmitted assignments sorted by deadline)
    upcoming = []
    for a in pending_assignments:
        due = a.due_date.replace(tzinfo=timezone.utc) if a.due_date and a.due_date.tzinfo is None else a.due_date
        if due and due >= now_utc:
            due_pkt = due.astimezone(app_tz)
            now_pkt = now_utc.astimezone(app_tz)
            day_diff = (due_pkt.date() - now_pkt.date()).days
            if day_diff == 0:
                hours = max(0, int((due - now_utc).total_seconds() / 3600))
                date_str = f"Today ({hours}h left)" if hours > 0 else "Today (Due soon)"
            elif day_diff == 1:
                date_str = "Tomorrow"
            elif day_diff < 7:
                date_str = f"{day_diff} days"
            else:
                weeks = day_diff // 7
                date_str = f"{weeks} week{'s' if weeks > 1 else ''}"
            upcoming.append({"title": a.title, "date": date_str})
    upcoming = upcoming[:5]

    # Real recent activity
    activity = []
    if account and account.last_synced_at:
        synced_at = account.last_synced_at if account.last_synced_at.tzinfo else account.last_synced_at.replace(tzinfo=timezone.utc)
        synced_pkt = synced_at.astimezone(app_tz)
        activity.append({
            "text": f"Classroom sync: {course_count} courses, {total_count} assignments",
            "time": f"Synced {synced_pkt.strftime('%I:%M %p PKT')}",
        })
        activity.append({
            "text": f"Google account linked ({account.google_email})",
            "time": "Active",
        })
    if completed_count > 0:
        activity.append({
            "text": f"{completed_count} assignments turned in / completed",
            "time": "Classroom",
        })
    if overdue_count > 0:
        activity.append({
            "text": f"{overdue_count} assignment requires attention (overdue)",
            "time": "Attention",
        })

    # 7-day workload distribution from real assignments
    days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    counts_by_dow = {day: 0 for day in days_of_week}
    for a in assignments:
        if a.due_date:
            due = a.due_date if a.due_date.tzinfo else a.due_date.replace(tzinfo=timezone.utc)
            tz = ZoneInfo(a.course.time_zone) if (a.course and a.course.time_zone) else app_tz
            dow_str = due.astimezone(tz).strftime("%a")
            if dow_str in counts_by_dow:
                counts_by_dow[dow_str] += 1

    chart_data = [{"day": day, "value": counts_by_dow[day]} for day in days_of_week]

    return {
        "is_demo": False,
        "authenticated": True,
        "google_connected": account is not None,
        "google_email": account.google_email if account else None,
        "last_synced_at": account.last_synced_at.isoformat() if account and account.last_synced_at else None,
        "metrics": {
            "total_assignments": total_count,
            "pending_assignments": pending_count,
            "due_today": due_today_count,
            "due_today_total": due_today_total,
            "overdue": overdue_count,
            "completed": completed_count,
            "awaiting_approval": awaiting_approval_count,
            "active_courses": course_count,
        },
        "stats": stats,
        "assignments": rows,
        "recentActivity": activity if activity else [{"text": "Connected to Google Classroom", "time": "Just now"}],
        "upcomingDeadlines": upcoming if upcoming else [{"title": "No pending deadlines", "date": "Clear"}],
        "chartData": chart_data,
    }


@router.get("/dashboard/overview")
def get_dashboard_overview(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if isinstance(user_id, int) else None
    if user is None:
        user = db.scalar(select(User).order_by(User.id.desc()))
        if user is None:
            return DEMO_DATA

    account = get_user_google_account(db, user.id)
    if account is None:
        return DEMO_DATA

    return _compute_dashboard_data(user, db)


@router.get("/dashboard/stats")
def get_dashboard_stats(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if isinstance(user_id, int) else None
    if user is None:
        user = db.scalar(select(User).order_by(User.id.desc()))
        if user is None:
            return {
                "is_demo": True,
                "total_assignments": 38,
                "pending_assignments": 12,
                "due_today": 4,
                "overdue": 3,
                "completed": 18,
                "awaiting_approval": 7,
                "active_courses": 6,
                "stats": DEMO_DATA["stats"],
            }

    account = get_user_google_account(db, user.id)
    if account is None:
        return {
            "is_demo": True,
            "total_assignments": 38,
            "pending_assignments": 12,
            "due_today": 4,
            "overdue": 3,
            "completed": 18,
            "awaiting_approval": 7,
            "active_courses": 6,
            "stats": DEMO_DATA["stats"],
        }

    data = _compute_dashboard_data(user, db)
    return {
        "is_demo": False,
        **data["metrics"],
        "stats": data["stats"],
    }
