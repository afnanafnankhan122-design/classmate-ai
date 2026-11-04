from datetime import datetime, UTC

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    roll_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(150), nullable=True)
    semester: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    google_accounts: Mapped[list["GoogleAccount"]] = relationship(back_populates="user")
    courses: Mapped[list["Course"]] = relationship(back_populates="user")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="user")
    ai_activity: Mapped[list["AIActivity"]] = relationship(back_populates="user")
