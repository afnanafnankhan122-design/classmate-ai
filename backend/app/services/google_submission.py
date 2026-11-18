from datetime import UTC, datetime
from io import BytesIO

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import Assignment, AssignmentDraftVersion, AssignmentExport
from app.models.approval import Approval
from app.models.google_account import GoogleAccount
from app.models.submission import Submission
from app.services.google_oauth import (
    CLASSROOM_STUDENT_READ_SCOPES,
    CLASSROOM_WRITE_SCOPES,
    DRIVE_FILE_SCOPE,
    get_classroom_credentials,
    is_google_insufficient_permissions,
    missing_google_scopes,
)
from google.auth.exceptions import RefreshError


class GoogleSubmissionError(RuntimeError):
    pass


class SubmissionPrerequisiteError(ValueError):
    pass


def submit_approved_assignment(db: Session, assignment: Assignment) -> dict[str, str]:
    try:
        return _submit_approved_assignment(db, assignment)
    except HttpError as exc:
        if is_google_insufficient_permissions(exc):
            raise SubmissionPrerequisiteError(
                "Google Classroom denied the student submission permissions. Reconnect Google "
                "and approve the required student coursework and Drive permissions."
            ) from exc
        raise GoogleSubmissionError(
            "Google Classroom could not complete or confirm the submission. Try again."
        ) from exc
    except RefreshError as exc:
        raise SubmissionPrerequisiteError(
            "Google authorization could not be refreshed. Reconnect your Google account "
            "before submitting."
        ) from exc


def _submit_approved_assignment(db: Session, assignment: Assignment) -> dict[str, str]:
    if not assignment.google_assignment_id or assignment.course is None:
        raise SubmissionPrerequisiteError("This assignment is not linked to Google Classroom.")

    version = db.scalar(
        select(AssignmentDraftVersion)
        .where(AssignmentDraftVersion.assignment_id == assignment.id)
        .order_by(AssignmentDraftVersion.version.desc())
        .limit(1)
    )
    if version is None:
        raise SubmissionPrerequisiteError("Save the assignment draft before submitting it.")
    approval = db.scalar(
        select(Approval).where(
            Approval.assignment_id == assignment.id,
            Approval.document_version == version.version,
            Approval.approval_status == "approved",
        )
    )
    if approval is None:
        raise SubmissionPrerequisiteError("Explicit approval of the latest draft is required.")

    exported_pdf = db.scalar(
        select(AssignmentExport)
        .where(
            AssignmentExport.assignment_id == assignment.id,
            AssignmentExport.draft_version_id == version.id,
            AssignmentExport.file_format == "pdf",
        )
        .order_by(AssignmentExport.created_at.desc())
        .limit(1)
    )
    if exported_pdf is None or not exported_pdf.file_content:
        raise SubmissionPrerequisiteError("Generate a PDF for the approved latest draft first.")

    account = db.scalar(
        select(GoogleAccount).where(GoogleAccount.user_id == assignment.user_id)
    )
    if account is None:
        raise SubmissionPrerequisiteError("Connect Google Classroom before submitting.")
    granted_scopes = set(account.authorized_scopes or [])
    required_scopes = {
        *CLASSROOM_STUDENT_READ_SCOPES,
        *CLASSROOM_WRITE_SCOPES,
        DRIVE_FILE_SCOPE,
    }
    if missing_google_scopes(granted_scopes, required_scopes):
        raise SubmissionPrerequisiteError(
            "Reconnect Google Classroom and approve the requested submission permissions."
        )

    credentials = get_classroom_credentials(db, account)
    classroom = build("classroom", "v1", credentials=credentials, cache_discovery=False)
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    course_id = assignment.course.google_course_id
    coursework_id = assignment.google_assignment_id
    google_submissions = (
        classroom.courses()
        .courseWork()
        .studentSubmissions()
        .list(courseId=course_id, courseWorkId=coursework_id, userId="me")
        .execute()
        .get("studentSubmissions", [])
    )
    google_submission = next(
        (item for item in google_submissions if item.get("id")),
        None,
    )
    if google_submission is None:
        raise SubmissionPrerequisiteError("Google Classroom did not return your submission.")

    local_submission = db.scalar(
        select(Submission)
        .where(
            Submission.assignment_id == assignment.id,
            Submission.draft_version_id == version.id,
        )
        .order_by(Submission.id.desc())
        .limit(1)
    )
    if local_submission is None:
        local_submission = Submission(
            assignment_id=assignment.id,
            draft_version_id=version.id,
            google_submission_id=google_submission["id"],
            submission_status="preparing",
        )
        db.add(local_submission)
        db.commit()
        db.refresh(local_submission)

    if google_submission.get("state") == "TURNED_IN":
        _mark_submitted(db, assignment, local_submission)
        return {"status": "submitted", "google_submission_id": google_submission["id"]}

    if local_submission.google_file_id:
        drive_file_id = local_submission.google_file_id
    else:
        search_query = (
            f"appProperties has {{ key='classmateAssignmentId' and value='{assignment.id}' }} "
            f"and appProperties has {{ key='classmateDraftVersionId' and value='{version.id}' }}"
        )
        existing_file = (
            drive.files()
            .list(q=search_query, spaces="drive", pageSize=1, fields="files(id)")
            .execute()
            .get("files", [])
        )
        if existing_file:
            drive_file_id = existing_file[0].get("id")
        else:
            uploaded_file = (
                drive.files()
                .create(
                    body={
                        "name": f"{assignment.title}.pdf",
                        "mimeType": "application/pdf",
                        "appProperties": {
                            "classmateAssignmentId": str(assignment.id),
                            "classmateDraftVersionId": str(version.id),
                        },
                    },
                    media_body=MediaIoBaseUpload(
                        BytesIO(exported_pdf.file_content),
                        mimetype="application/pdf",
                        resumable=True,
                    ),
                    fields="id",
                )
                .execute()
            )
            drive_file_id = uploaded_file.get("id")
        if not drive_file_id:
            raise GoogleSubmissionError("Google Drive did not confirm the PDF upload.")
        local_submission.google_file_id = drive_file_id
        local_submission.google_submission_id = google_submission["id"]
        local_submission.submission_status = "ready_to_submit"
        db.commit()

    assignment_submission = google_submission.get("assignmentSubmission") or {}
    existing_attachments = assignment_submission.get("attachments", [])
    already_attached = any(
        attachment.get("driveFile", {}).get("id") == drive_file_id
        for attachment in existing_attachments
    )
    if not already_attached:
        (
            classroom.courses()
            .courseWork()
            .studentSubmissions()
            .modifyAttachments(
                courseId=course_id,
                courseWorkId=coursework_id,
                id=google_submission["id"],
                body={"addAttachments": [{"driveFile": {"id": drive_file_id}}]},
            )
            .execute()
        )

    (
        classroom.courses()
        .courseWork()
        .studentSubmissions()
        .turnIn(courseId=course_id, courseWorkId=coursework_id, id=google_submission["id"])
        .execute()
    )
    verified = (
        classroom.courses()
        .courseWork()
        .studentSubmissions()
        .get(courseId=course_id, courseWorkId=coursework_id, id=google_submission["id"])
        .execute()
    )
    if verified.get("state") != "TURNED_IN":
        raise GoogleSubmissionError("Google Classroom has not confirmed the submission yet.")

    _mark_submitted(db, assignment, local_submission)
    return {"status": "submitted", "google_submission_id": google_submission["id"]}


def _mark_submitted(
    db: Session,
    assignment: Assignment,
    submission: Submission,
) -> None:
    now = datetime.now(UTC)
    submission.submission_status = "submitted"
    submission.submitted_at = now
    assignment.submission_status = "turned_in"
    assignment.processing_status = "submitted"
    db.commit()
