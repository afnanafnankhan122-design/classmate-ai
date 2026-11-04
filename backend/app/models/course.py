from datetime import datetime, UTC

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("user_id", "google_course_id", name="uq_course_user_google_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    google_course_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    course_name: Mapped[str] = mapped_column(String(255), nullable=False)
    course_section: Mapped[str | None] = mapped_column(String(150), nullable=True)
    course_state: Mapped[str | None] = mapped_column(String(50), nullable=True, default="ACTIVE")
    alternate_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    time_zone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    user: Mapped["User"] = relationship(back_populates="courses")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="course")
