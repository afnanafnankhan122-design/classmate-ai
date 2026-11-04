"""Student notifications router — real event and deadline notification management."""

from datetime import datetime, UTC, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.core.config import settings
from app.database.dependencies import get_db
from app.models.assignment import Assignment
from app.models.notification import Notification
from app.models.user import User

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """List recent notifications for the authenticated student, with automatic deadline reminders."""
    now_utc = datetime.now(timezone.utc)
    app_tz = ZoneInfo(settings.app_timezone)

    # Check for assignments due today to auto-generate timely reminder if not already generated today
    today_assignments = db.scalars(
        select(Assignment)
        .where(
            Assignment.user_id == user.id,
            Assignment.is_demo.is_(False),
            Assignment.submission_status.in_(["assigned", "unsubmitted", "not_started"]),
            Assignment.due_date.is_not(None),
        )
    ).all()

    for a in today_assignments:
        due_utc = a.due_date if a.due_date.tzinfo else a.due_date.replace(tzinfo=timezone.utc)
        due_local = due_utc.astimezone(app_tz)
        if due_local.date() == datetime.now(app_tz).date():
            # Check if reminder already exists
            existing = db.scalar(
                select(Notification).where(
                    Notification.user_id == user.id,
                    Notification.category == "due_today",
                    Notification.title.ilike(f"%{a.title}%"),
                )
            )
            if not existing:
                notif = Notification(
                    user_id=user.id,
                    title=f"Due Today: {a.title}",
                    message=f"Assignment is due today at {a.due_time or due_local.strftime('%I:%M %p')} PKT.",
                    category="due_today",
                    link=a.alternate_link,
                    is_read=False,
                )
                db.add(notif)
                db.commit()

    # Fetch stored notifications
    notifications = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(40)
    ).all()

    unread_count = sum(1 for n in notifications if not n.is_read)

    return {
        "notifications": [
            {
                "id": n.id,
                "title": n.title,
                "message": n.message,
                "category": n.category,
                "link": n.link,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ],
        "unread_count": unread_count,
    }


@router.patch("/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Mark a single notification as read with strict ownership check."""
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found.")

    notification.is_read = True
    db.commit()
    return {"status": "ok", "id": notification_id, "is_read": True}


@router.post("/read-all")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Mark all notifications as read for the authenticated student."""
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return {"status": "ok"}

