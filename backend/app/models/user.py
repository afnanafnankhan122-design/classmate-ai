from datetime import datetime, UTC

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    google_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    auth_provider: Mapped[str] = mapped_column(String(50), default="email", server_default="email", nullable=False)
    auth_version: Mapped[int] = mapped_column(default=0, nullable=False)
    roll_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(150), nullable=True)
    semester: Mapped[str | None] = mapped_column(String(40), nullable=True)
    terms_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    privacy_policy_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    privacy_acknowledged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    google_accounts: Mapped[list["GoogleAccount"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    courses: Mapped[list["Course"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    ai_activity: Mapped[list["AIActivity"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    device_sessions: Mapped[list["DeviceSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user", cascade="all, delete-orphan")
