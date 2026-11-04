from fastapi import APIRouter, Depends, HTTPException, Query
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from zoneinfo import ZoneInfoNotFoundError

from app.core.config import settings
from app.database.dependencies import get_db
from app.models.assignment import Assignment
from app.models.course import Course
from app.models.google_account import GoogleAccount
from app.models.user import User
from app.services.google_classroom import (
    classroom_assignment_dict,
    sync_classroom_data,
)
from app.services.google_oauth import (
    GoogleIntegrationNotConfigured,
    delete_google_account,
    get_classroom_credentials,
    get_user_google_account,
    google_http_status,
)
from app.api.routes.auth import get_current_user

router = APIRouter(prefix="/classroom", tags=["Google Classroom"])


def _get_connected_account(db: Session, user: User) -> GoogleAccount:
    account = get_user_google_account(db, user.id)
    if account is None:
        raise HTTPException(
            status_code=409,
            detail="Connect a Google account before accessing Classroom.",
        )
    return account


def _get_credentials(db: Session, account: GoogleAccount) -> Credentials:
    try:
        return get_classroom_credentials(db, account)
    except RefreshError as exc:
        raise HTTPException(
            status_code=401,
            detail="Google authorization expired or was revoked. Reconnect your account.",
        ) from exc
    except GoogleIntegrationNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=502,
            detail="Google authentication could not be refreshed. Try reconnecting.",
        ) from exc


def _google_api_error(
    error: HttpError,
    db: Session,
    account: GoogleAccount,
) -> HTTPException:
    status = google_http_status(error)
    if status == 401:
        return HTTPException(
            status_code=401,
            detail="Google authorization expired or was revoked. Reconnect your account.",
        )
    if status == 403:
        err_msg = str(error)
        if "not been used in project" in err_msg or "disabled" in err_msg:
            return HTTPException(
                status_code=403,
                detail=(
                    "Google Classroom API is not enabled in your Google Cloud Console project. "
                    "Enable the 'Google Classroom API' in Google Cloud Console."
                ),
            )
        return HTTPException(
            status_code=403,
            detail=(
                "Google Classroom denied access. Check that the Google Classroom API is enabled "
                "in your Google Cloud Console project and that your account has permission to view courses."
            ),
        )
    if status == 404:
        return HTTPException(
            status_code=502,
            detail="A Classroom resource is no longer available. Try syncing again.",
        )
    if status == 429:
        return HTTPException(
            status_code=429,
            detail="Google Classroom rate limit reached. Wait briefly, then sync again.",
        )
    if status is not None and status >= 500:
        return HTTPException(
            status_code=503,
            detail="Google Classroom is temporarily unavailable. Try syncing again later.",
        )
    return HTTPException(
        status_code=502,
        detail="Google Classroom could not complete the request. Try again later.",
    )


def _sync_if_requested(
    db: Session,
    user: User,
    account: GoogleAccount | None,
    auto_sync: bool,
) -> None:
    if account is None or (account.last_synced_at is not None and not auto_sync):
        return

    credentials = _get_credentials(db, account)
    try:
        sync_classroom_data(db, user.id, credentials)
    except HttpError as exc:
        raise _google_api_error(exc, db, account) from exc
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=502,
            detail="Google authentication failed while syncing Classroom.",
        ) from exc
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status_code=502,
            detail="Google returned an unsupported course timezone. Sync was not completed.",
        ) from exc
    db.refresh(account)


@router.post("/sync")
def sync_classrooms(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    account = _get_connected_account(db, user)
    credentials = _get_credentials(db, account)
    try:
        result = sync_classroom_data(db, user.id, credentials)
    except HttpError as exc:
        raise _google_api_error(exc, db, account) from exc
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=502,
            detail="Google authentication failed while syncing Classroom.",
        ) from exc
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status_code=502,
            detail="Google returned an unsupported course timezone. Sync was not completed.",
        ) from exc
    return {"status": "synced", **result}


@router.get("/courses")
def list_classroom_courses(
    auto_sync: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    account = get_user_google_account(db, user.id)
    _sync_if_requested(db, user, account, auto_sync)

    courses = db.scalars(
        select(Course)
        .where(Course.user_id == user.id, Course.is_active.is_(True))
        .order_by(Course.course_name)
    ).all()
    return {
        "courses": [
            {
                "id": course.google_course_id,
                "name": course.course_name,
                "section": course.course_section,
                "course_state": course.course_state or "ACTIVE",
                "alternate_link": course.alternate_link,
                "time_zone": course.time_zone,
            }
            for course in courses
        ],
        "last_synced_at": account.last_synced_at.isoformat() if account and account.last_synced_at else None,
    }


@router.get("/assignments")
def list_classroom_assignments(
    due_today: bool = Query(default=False),
    auto_sync: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    account = get_user_google_account(db, user.id)
    _sync_if_requested(db, user, account, auto_sync)

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
    items = [classroom_assignment_dict(assignment) for assignment in assignments]
    if due_today:
        items = [item for item in items if item["due_today"]]
    return {
        "assignments": items,
        "due_today_count": sum(1 for item in items if item["due_today"]),
        "timezone": settings.app_timezone,
        "last_synced_at": account.last_synced_at.isoformat() if account and account.last_synced_at else None,
    }
