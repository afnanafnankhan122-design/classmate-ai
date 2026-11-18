from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import Assignment, AssignmentDraftVersion


def save_assignment_version(
    db: Session,
    assignment: Assignment,
    content: str,
    source: str,
    note: str | None = None,
) -> AssignmentDraftVersion | None:
    latest_version = db.scalar(
        select(AssignmentDraftVersion)
        .where(AssignmentDraftVersion.assignment_id == assignment.id)
        .order_by(AssignmentDraftVersion.version.desc())
        .limit(1)
    )
    if (
        latest_version is not None
        and latest_version.content == content
        and assignment.draft_content == content
    ):
        return None

    version = AssignmentDraftVersion(
        assignment_id=assignment.id,
        version=(latest_version.version if latest_version else 0) + 1,
        content=content,
        source=source,
        note=note,
    )
    assignment.draft_content = content
    db.add(version)
    db.commit()
    db.refresh(version)
    return version
