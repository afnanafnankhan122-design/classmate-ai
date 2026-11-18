from datetime import datetime, UTC

from typing import Any

from sqlalchemy import JSON, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("course_id", "google_assignment_id", name="uq_assignment_course_google_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    google_assignment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(nullable=True)
    due_time: Mapped[str | None] = mapped_column(String(50), nullable=True)
    alternate_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    max_points: Mapped[float | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="new", nullable=False)
    submission_status: Mapped[str] = mapped_column(String(50), default="not_started", nullable=False)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    draft_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_status: Mapped[str] = mapped_column(
        String(50),
        default="pending",
        server_default="pending",
        nullable=False,
    )
    processing_attempts: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    processing_claim_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_next_attempt_at: Mapped[datetime | None] = mapped_column(nullable=True)
    processing_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    is_demo: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    user: Mapped["User"] = relationship(back_populates="assignments")
    course: Mapped["Course"] = relationship(back_populates="assignments")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="assignment")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="assignment")
    documents: Mapped[list["AssignmentDocument"]] = relationship(back_populates="assignment")
    draft_versions: Mapped[list["AssignmentDraftVersion"]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="AssignmentDraftVersion.version.desc()",
    )
    exports: Mapped[list["AssignmentExport"]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="AssignmentExport.created_at.desc()",
    )
    ai_activity: Mapped[list["AIActivity"]] = relationship(back_populates="assignment")


class AssignmentDraftVersion(Base):
    __tablename__ = "assignment_draft_versions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "version", name="uq_assignment_draft_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    assignment: Mapped[Assignment] = relationship(back_populates="draft_versions")
    exports: Mapped[list["AssignmentExport"]] = relationship(back_populates="draft_version")


class AssignmentExport(Base):
    __tablename__ = "assignment_exports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    draft_version_id: Mapped[int] = mapped_column(
        ForeignKey("assignment_draft_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)
    file_content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    assignment: Mapped[Assignment] = relationship(back_populates="exports")
    draft_version: Mapped[AssignmentDraftVersion] = relationship(back_populates="exports")


class AssignmentDocument(Base):
    __tablename__ = "assignment_documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    original_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generated_pdf: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    assignment: Mapped[Assignment] = relationship(back_populates="documents")
