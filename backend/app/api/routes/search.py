"""Search endpoint — searches real assignments and courses for the authenticated user."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.database.dependencies import get_db
from app.models.assignment import Assignment
from app.models.course import Course
from app.api.routes.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(
    q: str = Query(default="", description="Search term"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    q = q.strip()
    if not q or len(q) < 2:
        return {"query": q, "assignments": [], "courses": []}

    term = f"%{q}%"

    assignments = db.scalars(
        select(Assignment)
        .options(selectinload(Assignment.course))
        .join(Course, Assignment.course_id == Course.id)
        .where(
            Assignment.user_id == user.id,
            Assignment.is_demo.is_(False),
            Assignment.google_assignment_id.is_not(None),
            Course.is_active.is_(True),
            or_(
                Assignment.title.ilike(term),
                Assignment.description.ilike(term),
            ),
        )
        .order_by(Assignment.due_date.asc().nulls_last(), Assignment.title)
        .limit(20)
    ).all()

    courses = db.scalars(
        select(Course)
        .where(
            Course.user_id == user.id,
            Course.is_active.is_(True),
            or_(
                Course.course_name.ilike(term),
                Course.course_section.ilike(term),
            ),
        )
        .order_by(Course.course_name)
        .limit(10)
    ).all()

    assignment_results = []
    app_tz = ZoneInfo("Asia/Karachi")
    for a in assignments:
        deadline_str = None
        due_iso = None
        if a.due_date:
            due_utc = a.due_date if a.due_date.tzinfo else a.due_date.replace(tzinfo=timezone.utc)
            local_dt = due_utc.astimezone(app_tz)
            due_iso = local_dt.isoformat()
            if a.due_time:
                time_str = (
                    a.due_time
                    if ("AM" in a.due_time or "PM" in a.due_time)
                    else local_dt.strftime("%I:%M %p")
                )
                deadline_str = f"{local_dt.strftime('%b %d')}, {time_str} PKT"
            else:
                deadline_str = f"{local_dt.strftime('%b %d, %Y')} (No due time) PKT"

        assignment_results.append({
            "id": a.id,
            "title": a.title,
            "course": a.course.course_name if a.course else "Classroom",
            "due_date": due_iso,
            "deadline": deadline_str,
            "submission_status": a.submission_status or "assigned",
            "alternate_link": a.alternate_link,
        })

    course_results = []
    for c in courses:
        course_results.append({
            "id": c.google_course_id,
            "name": c.course_name,
            "section": c.course_section,
            "alternate_link": c.alternate_link,
        })

    return {
        "query": q,
        "assignments": assignment_results,
        "courses": course_results,
    }

