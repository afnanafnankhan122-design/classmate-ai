from datetime import UTC, date, datetime, timedelta, timezone
import logging
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.assignment import Assignment, AssignmentDraftVersion, AssignmentExport
from app.models.notification import Notification
from app.services.assignment_ai import create_assignment_suggestion
from app.services.assignment_documents import make_pdf
from app.services.assignment_versions import save_assignment_version
from app.services.entitlements import get_license_status, require_active_license

logger = logging.getLogger(__name__)

KARACHI = ZoneInfo("Asia/Karachi")
CLAIM_TIMEOUT = timedelta(minutes=15)
RETRY_DELAY = timedelta(minutes=5)
MAX_ATTEMPTS = 5


def due_date_in_karachi(due_at: datetime | None) -> date | None:
    if due_at is None:
        return None
    aware_due = due_at.replace(tzinfo=timezone.utc) if due_at.tzinfo is None else due_at
    return aware_due.astimezone(KARACHI).date()


def process_due_assignments(db: Session, now: datetime | None = None) -> int:
    """Claim and process each connected student's assignment due today, once at a time."""
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    current_time = current_time.astimezone(UTC)
    today = current_time.astimezone(KARACHI).date()
    now_utc_naive = current_time.replace(tzinfo=None)
    stale_before = (current_time - CLAIM_TIMEOUT).replace(tzinfo=None)

    assignments = db.scalars(
        select(Assignment)
        .options(selectinload(Assignment.course), selectinload(Assignment.user))
        .where(Assignment.is_demo.is_(False), Assignment.due_date.is_not(None))
    ).all()

    processed = 0
    for assignment in assignments:
        if assignment.user is None:
            continue
        try:
            license_status = get_license_status(db, assignment.user)
        except Exception as exc:
            logger.warning(
                "Due-date assignment skipped: assignment_id=%s license_check_error_type=%s",
                assignment.id,
                type(exc).__name__,
            )
            continue
        if not license_status.active:
            continue
        if assignment.submission_status in {"turned_in", "graded"}:
            continue
        due_day = due_date_in_karachi(assignment.due_date)
        if due_day is None:
            continue
        if due_day < today:
            stale_processing = (
                assignment.processing_status == "processing"
                and assignment.processing_started_at is not None
                and assignment.processing_started_at <= stale_before
            )
            if assignment.processing_status in {"pending", "failed", "overdue"} or stale_processing:
                assignment.processing_status = "overdue"
                assignment.processing_started_at = None
                assignment.processing_claim_id = None
            continue
        if due_day > today:
            continue
        claim_id = _claim_assignment(db, assignment, now_utc_naive, stale_before)
        if claim_id is not None:
            processed += 1
            _process_claimed_assignment(db, assignment.id, now_utc_naive, claim_id)
    db.commit()
    return processed


def _claim_assignment(
    db: Session,
    assignment: Assignment,
    now_utc_naive: datetime,
    stale_before: datetime,
) -> str | None:
    claim_id = uuid4().hex
    retry_ready = or_(
        Assignment.processing_next_attempt_at.is_(None),
        Assignment.processing_next_attempt_at <= now_utc_naive,
    )
    claimable = or_(
        Assignment.processing_status.in_(["pending", "overdue"]),
        and_(Assignment.processing_status == "failed", retry_ready),
        and_(
            Assignment.processing_status == "processing",
            Assignment.processing_started_at.is_not(None),
            Assignment.processing_started_at <= stale_before,
        ),
    )
    result = db.execute(
        update(Assignment)
        .where(Assignment.id == assignment.id, claimable, Assignment.processing_attempts < MAX_ATTEMPTS)
        .values(
            processing_status="processing",
            processing_attempts=Assignment.processing_attempts + 1,
            processing_started_at=now_utc_naive,
            processing_claim_id=claim_id,
            processing_next_attempt_at=None,
            processing_error=None,
        )
    )
    db.commit()
    return claim_id if result.rowcount == 1 else None


def _process_claimed_assignment(
    db: Session,
    assignment_id: int,
    now_utc_naive: datetime,
    claim_id: str,
) -> None:
    assignment = db.scalar(
        select(Assignment)
        .options(selectinload(Assignment.course), selectinload(Assignment.user))
        .where(Assignment.id == assignment_id)
    )
    if assignment is None:
        return
    try:
        user = assignment.user
        require_active_license(db, user)
        latest_version = db.scalar(
            select(AssignmentDraftVersion)
            .where(AssignmentDraftVersion.assignment_id == assignment.id)
            .order_by(AssignmentDraftVersion.version.desc())
            .limit(1)
        )
        if assignment.draft_content and assignment.draft_content.strip():
            # A pre-existing saved draft may contain student edits; never replace it in
            # the background. The generated review PDF uses the same latest saved text.
            version = latest_version
            if version is None or version.content != assignment.draft_content:
                version = save_assignment_version(
                    db,
                    assignment,
                    assignment.draft_content,
                    "legacy",
                    "Saved draft preserved during due-date processing",
                )
        else:
            if not assignment.description or not assignment.description.strip():
                raise ValueError("Assignment instructions are missing.")
            content = create_assignment_suggestion(
                title=assignment.title,
                instructions=assignment.description,
                course=assignment.course.course_name if assignment.course else None,
                attachments=assignment.attachments or [],
                current_draft=None,
                action="generate",
                length="standard",
                style="academic",
                selected_text=None,
                instruction=None,
            )
            version = save_assignment_version(
                db,
                assignment,
                content,
                "ai",
                "Automatically generated on the assignment due date",
            )
            if version is None:
                version = db.scalar(
                    select(AssignmentDraftVersion)
                    .where(AssignmentDraftVersion.assignment_id == assignment.id)
                    .order_by(AssignmentDraftVersion.version.desc())
                    .limit(1)
                )

        current_claim_id = db.scalar(
            select(Assignment.processing_claim_id).where(
                Assignment.id == assignment_id,
                Assignment.processing_claim_id == claim_id,
            )
        )
        if current_claim_id is None:
            db.rollback()
            return
        if version is None or not version.content.strip():
            raise ValueError("AI generation did not produce a saved assignment draft.")
        pdf = make_pdf(assignment, user, version.content)
        db.add(
            AssignmentExport(
                assignment_id=assignment.id,
                draft_version_id=version.id,
                file_format="pdf",
                file_content=pdf,
            )
        )
        assignment.processing_status = "ready_for_review"
        assignment.processing_started_at = None
        assignment.processing_claim_id = None
        assignment.processing_next_attempt_at = None
        assignment.processing_error = None
        assignment.processed_at = now_utc_naive

        existing_notification = db.scalar(
            select(Notification.id).where(
                Notification.assignment_id == assignment.id,
                Notification.category == "assignment_ready",
            )
        )
        if existing_notification is None:
            db.add(
                Notification(
                    user_id=assignment.user_id,
                    assignment_id=assignment.id,
                    title=f"Assignment ready to review: {assignment.title}",
                    message="Your due-today assignment draft and PDF are ready. Review and edit them before approving submission.",
                    category="assignment_ready",
                    link=assignment.alternate_link,
                )
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_assignment = db.get(Assignment, assignment_id)
        if failed_assignment is not None and failed_assignment.processing_claim_id == claim_id:
            failed_assignment.processing_status = "failed"
            failed_assignment.processing_started_at = None
            failed_assignment.processing_claim_id = None
            if isinstance(exc, ValueError):
                error = str(exc)
            elif isinstance(exc, HTTPException) and isinstance(exc.detail, str):
                error = exc.detail
            else:
                error = f"Processing failed ({type(exc).__name__})."
            failed_assignment.processing_error = error[:500]
            failed_assignment.processing_next_attempt_at = (
                now_utc_naive + RETRY_DELAY
                if failed_assignment.processing_attempts < MAX_ATTEMPTS
                else None
            )
            if failed_assignment.processing_attempts >= MAX_ATTEMPTS:
                failure_notification = db.scalar(
                    select(Notification.id).where(
                        Notification.assignment_id == assignment_id,
                        Notification.category == "assignment_failed",
                    )
                )
                if failure_notification is None:
                    db.add(
                        Notification(
                            user_id=failed_assignment.user_id,
                            assignment_id=failed_assignment.id,
                            title=f"Assignment needs attention: {failed_assignment.title}",
                            message="Automatic processing could not complete after several attempts. Review the assignment in your workspace.",
                            category="assignment_failed",
                        )
                    )
            db.commit()
        logger.warning(
            "Due-date assignment processing failed: assignment_id=%s error_type=%s",
            assignment_id,
            type(exc).__name__,
        )
