from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import get_current_user
from app.api.schemas.assignment import (
    DraftUpdateRequest,
    RestoreVersionRequest,
    SuggestionRequest,
)
from app.core.auth_security import auth_rate_limiter
from app.database.dependencies import get_db
from app.models.assignment import Assignment, AssignmentDraftVersion, AssignmentExport
from app.models.approval import Approval
from app.models.user import User
from app.services.assignment_ai import create_assignment_suggestion
from app.services.assignment_documents import (
    make_docx,
    make_pdf,
    make_schedule_csv,
    safe_filename,
)
from app.services.assignment_versions import save_assignment_version
from app.services.entitlements import get_license_status, require_active_license
from app.services.google_submission import (
    GoogleSubmissionError,
    SubmissionPrerequisiteError,
    submit_approved_assignment,
)

router = APIRouter(prefix="/assignments", tags=["assignments"])


def _owned_assignment(db: Session, user: User, assignment_id: int) -> Assignment:
    assignment = db.scalar(
        select(Assignment)
        .options(selectinload(Assignment.course))
        .where(
            Assignment.id == assignment_id,
            Assignment.user_id == user.id,
            Assignment.is_demo.is_(False),
        )
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found.")
    return assignment


def _version_dict(version: AssignmentDraftVersion) -> dict:
    return {
        "id": version.id,
        "version": version.version,
        "content": version.content,
        "source": version.source,
        "note": version.note,
        "created_at": version.created_at.isoformat(),
    }


def _save_version(
    db: Session,
    assignment: Assignment,
    content: str,
    source: str,
    note: str | None = None,
) -> AssignmentDraftVersion | None:
    return save_assignment_version(db, assignment, content, source, note)


@router.get("/{assignment_id}/workspace")
def get_assignment_workspace(
    assignment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    assignment = _owned_assignment(db, user, assignment_id)
    versions = db.scalars(
        select(AssignmentDraftVersion)
        .where(AssignmentDraftVersion.assignment_id == assignment.id)
        .order_by(AssignmentDraftVersion.version.desc())
        .limit(50)
    ).all()
    exports = db.scalars(
        select(AssignmentExport)
        .where(AssignmentExport.assignment_id == assignment.id)
        .order_by(AssignmentExport.created_at.desc())
        .limit(25)
    ).all()
    latest_version = db.scalar(
        select(AssignmentDraftVersion)
        .where(AssignmentDraftVersion.assignment_id == assignment.id)
        .order_by(AssignmentDraftVersion.version.desc())
        .limit(1)
    )
    approval = None
    if latest_version is not None:
        approval = db.scalar(
            select(Approval).where(
                Approval.assignment_id == assignment.id,
                Approval.document_version == latest_version.version,
                Approval.approval_status == "approved",
            )
        )
    license_status = get_license_status(db, user)
    return {
        "license": {
            "status": license_status.status,
            "active": license_status.active,
        },
        "assignment": {
            "id": assignment.id,
            "title": assignment.title,
            "instructions": assignment.description,
            "course": assignment.course.course_name if assignment.course else None,
            "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
            "draft_content": assignment.draft_content,
            "attachments": assignment.attachments or [],
            "processing_status": assignment.processing_status,
            "processing_error": assignment.processing_error,
            "submission_status": assignment.submission_status,
            "approved": approval is not None,
            "latest_version": latest_version.version if latest_version else None,
        },
        "student": {
            "full_name": user.full_name,
            "roll_number": user.roll_number,
            "department": user.department,
            "semester": user.semester,
        },
        "versions": [_version_dict(version) for version in versions],
        "exports": [
            {
                "id": export.id,
                "version": export.draft_version.version,
                "format": export.file_format,
                "created_at": export.created_at.isoformat(),
            }
            for export in exports
        ],
    }


@router.put("/{assignment_id}/draft")
def update_assignment_draft(
    assignment_id: int,
    data: DraftUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    assignment = _owned_assignment(db, user, assignment_id)
    require_active_license(db, user)
    version = _save_version(db, assignment, data.content, data.source)
    if version is not None and assignment.processing_status in {"ready_for_review", "approved"}:
        assignment.processing_status = "editing"
        db.commit()
    return {
        "status": "saved",
        "draft_content": assignment.draft_content,
        "version": _version_dict(version) if version else None,
    }


@router.post("/{assignment_id}/suggestions")
def suggest_assignment_content(
    assignment_id: int,
    data: SuggestionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    assignment = _owned_assignment(db, user, assignment_id)
    require_active_license(db, user)
    if not auth_rate_limiter.is_allowed(
        f"assignment-ai:{user.id}",
        max_attempts=10,
        window_seconds=60,
    ):
        raise HTTPException(
            status_code=429,
            detail="Too many AI requests. Wait a minute before trying again.",
        )
    if data.action == "rewrite" and not assignment.draft_content:
        raise HTTPException(status_code=409, detail="Save a draft before requesting a rewrite.")
    if data.selected_text and not assignment.draft_content:
        raise HTTPException(status_code=409, detail="Save a draft before rewriting a section.")
    suggestion = create_assignment_suggestion(
        title=assignment.title,
        instructions=assignment.description,
        course=assignment.course.course_name if assignment.course else None,
        attachments=assignment.attachments or [],
        current_draft=assignment.draft_content,
        action=data.action,
        length=data.length,
        style=data.style,
        selected_text=data.selected_text,
        instruction=data.instruction,
    )
    return {"suggestion": suggestion}


@router.post("/{assignment_id}/versions/restore")
def restore_assignment_version(
    assignment_id: int,
    data: RestoreVersionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    assignment = _owned_assignment(db, user, assignment_id)
    require_active_license(db, user)
    version = db.scalar(
        select(AssignmentDraftVersion).where(
            AssignmentDraftVersion.id == data.version_id,
            AssignmentDraftVersion.assignment_id == assignment.id,
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Draft version not found.")
    restored = _save_version(
        db,
        assignment,
        version.content,
        "restored",
        f"Restored from version {version.version}",
    )
    if restored is not None and assignment.processing_status in {"ready_for_review", "approved"}:
        assignment.processing_status = "editing"
        db.commit()
    return {
        "status": "restored",
        "draft_content": assignment.draft_content,
        "version": _version_dict(restored) if restored else _version_dict(version),
    }


@router.get("/{assignment_id}/documents/{file_format}")
def download_assignment_document(
    assignment_id: int,
    file_format: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    if file_format not in {"pdf", "docx", "csv"}:
        raise HTTPException(status_code=404, detail="Document format not supported.")
    assignment = _owned_assignment(db, user, assignment_id)
    require_active_license(db, user)
    if not assignment.draft_content or not assignment.draft_content.strip():
        raise HTTPException(status_code=409, detail="Save assignment content before exporting.")

    latest_version = db.scalar(
        select(AssignmentDraftVersion)
        .where(AssignmentDraftVersion.assignment_id == assignment.id)
        .order_by(AssignmentDraftVersion.version.desc())
        .limit(1)
    )
    if latest_version is None or latest_version.content != assignment.draft_content:
        latest_version = _save_version(
            db,
            assignment,
            assignment.draft_content,
            "legacy",
            "Initial version created from the saved draft during export",
        )
    if latest_version is None:
        raise HTTPException(status_code=409, detail="Save assignment content before exporting.")

    if file_format == "pdf":
        content = make_pdf(assignment, user, latest_version.content)
        media_type = "application/pdf"
    elif file_format == "docx":
        content = make_docx(assignment, user, latest_version.content)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        content = make_schedule_csv(latest_version.content)
        media_type = "text/csv; charset=utf-8"

    db.add(
        AssignmentExport(
            assignment_id=assignment.id,
            draft_version_id=latest_version.id,
            file_format=file_format,
            file_content=content,
        )
    )
    db.commit()
    export = db.scalar(
        select(AssignmentExport)
        .where(
            AssignmentExport.assignment_id == assignment.id,
            AssignmentExport.draft_version_id == latest_version.id,
            AssignmentExport.file_format == file_format,
        )
        .order_by(AssignmentExport.created_at.desc())
        .limit(1)
    )

    filename = f"{safe_filename(assignment.title)}.{file_format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Assignment-Version": str(latest_version.version),
            **({"X-Assignment-Export": str(export.id)} if export else {}),
        },
    )


@router.get("/{assignment_id}/exports/{export_id}")
def download_saved_export(
    assignment_id: int,
    export_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    assignment = _owned_assignment(db, user, assignment_id)
    require_active_license(db, user)
    export = db.scalar(
        select(AssignmentExport)
        .options(selectinload(AssignmentExport.draft_version))
        .where(
            AssignmentExport.id == export_id,
            AssignmentExport.assignment_id == assignment.id,
        )
    )
    if export is None or export.file_content is None:
        raise HTTPException(status_code=404, detail="Saved document not found.")
    media_type = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "csv": "text/csv; charset=utf-8",
    }.get(export.file_format)
    if media_type is None:
        raise HTTPException(status_code=415, detail="Saved document format is not supported.")
    return Response(
        content=export.file_content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{safe_filename(assignment.title)}.{export.file_format}"'
            ),
            "X-Assignment-Version": str(export.draft_version.version),
        },
    )


@router.post("/{assignment_id}/approve")
def approve_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    assignment = _owned_assignment(db, user, assignment_id)
    require_active_license(db, user)
    latest_version = db.scalar(
        select(AssignmentDraftVersion)
        .where(AssignmentDraftVersion.assignment_id == assignment.id)
        .order_by(AssignmentDraftVersion.version.desc())
        .limit(1)
    )
    if latest_version is None or not latest_version.content.strip():
        raise HTTPException(status_code=409, detail="Save an assignment draft before approving it.")
    latest_pdf = db.scalar(
        select(AssignmentExport.id).where(
            AssignmentExport.assignment_id == assignment.id,
            AssignmentExport.draft_version_id == latest_version.id,
            AssignmentExport.file_format == "pdf",
            AssignmentExport.file_content.is_not(None),
        )
    )
    if latest_pdf is None:
        raise HTTPException(
            status_code=409,
            detail="Generate or download a PDF for the latest draft before approving it.",
        )

    approval = db.scalar(
        select(Approval).where(
            Approval.assignment_id == assignment.id,
            Approval.document_version == latest_version.version,
        )
    )
    if approval is None:
        approval = Approval(
            assignment_id=assignment.id,
            document_version=latest_version.version,
            approval_status="approved",
            approved_at=datetime.now(UTC),
        )
        db.add(approval)
    else:
        approval.approval_status = "approved"
        approval.approved_at = datetime.now(UTC)
    assignment.processing_status = "approved"
    db.commit()
    return {
        "status": "approved",
        "document_version": latest_version.version,
        "message": "The latest PDF is approved. Submit it to Google Classroom when you are ready.",
    }


@router.post("/{assignment_id}/submit")
def submit_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    assignment = _owned_assignment(db, user, assignment_id)
    require_active_license(db, user)
    try:
        result = submit_approved_assignment(db, assignment)
    except SubmissionPrerequisiteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GoogleSubmissionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        **result,
        "message": "Google Classroom confirmed that your assignment was submitted.",
    }
