from datetime import UTC, datetime
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models.google_account import GoogleAccount
from app.models.user import User
from app.services.assignment_processing import process_due_assignments
from app.services.entitlements import get_license_status
from app.services.google_classroom import sync_classroom_data
from app.services.google_oauth import get_classroom_credentials

logger = logging.getLogger(__name__)


def sync_connected_classrooms() -> None:
    with SessionLocal() as db:
        accounts = db.scalars(select(GoogleAccount)).all()
        for account in accounts:
            try:
                user = db.get(User, account.user_id)
                if user is None:
                    logger.info(
                        "Scheduled Classroom sync skipped: account_id=%s reason=user_missing",
                        account.id,
                    )
                    continue
                license_status = get_license_status(db, user)
                if not license_status.active:
                    logger.info(
                        "Scheduled Classroom sync skipped: account_id=%s license_status=%s",
                        account.id,
                        license_status.status,
                    )
                    continue

                credentials = get_classroom_credentials(db, account)
                # Credential refresh can take time; recheck immediately before the
                # Google Classroom API call so a grant that expired meanwhile is not used.
                db.expire_all()
                user = db.get(User, account.user_id)
                if user is None:
                    logger.info(
                        "Scheduled Classroom sync skipped: account_id=%s reason=user_missing",
                        account.id,
                    )
                    continue
                license_status = get_license_status(db, user)
                if not license_status.active:
                    logger.info(
                        "Scheduled Classroom sync skipped: account_id=%s license_status=%s",
                        account.id,
                        license_status.status,
                    )
                    continue
                sync_classroom_data(db, account.user_id, credentials)
            except Exception as exc:
                logger.warning(
                    "Scheduled Classroom sync failed: account_id=%s error_type=%s",
                    account.id,
                    type(exc).__name__,
                )


def scheduled_due_assignment_scan() -> None:
    with SessionLocal() as db:
        process_due_assignments(db)


def create_classroom_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    now = datetime.now(UTC)
    scheduler.add_job(
        sync_connected_classrooms,
        trigger="interval",
        minutes=5,
        id="classmate-classroom-sync",
        next_run_time=now,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        scheduled_due_assignment_scan,
        trigger="interval",
        minutes=1,
        id="classmate-due-assignment-scan",
        next_run_time=now,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    return scheduler
