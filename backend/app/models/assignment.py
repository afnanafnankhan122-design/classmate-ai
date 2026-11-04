from datetime import datetime, UTC

from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
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
    is_demo: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    user: Mapped["User"] = relationship(back_populates="assignments")
    course: Mapped["Course"] = relationship(back_populates="assignments")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="assignment")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="assignment")
    documents: Mapped[list["AssignmentDocument"]] = relationship(back_populates="assignment")
    ai_activity: Mapped[list["AIActivity"]] = relationship(back_populates="assignment")


class AssignmentDocument(Base):
    __tablename__ = "assignment_documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    original_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generated_pdf: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    assignment: Mapped[Assignment] = relationship(back_populates="documents")
