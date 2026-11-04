from datetime import datetime, UTC

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    google_submission_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submission_status: Mapped[str] = mapped_column(String(50), default="not_submitted", nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    assignment: Mapped["Assignment"] = relationship(back_populates="submissions")
