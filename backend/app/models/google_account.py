from datetime import datetime, UTC

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class GoogleAccount(Base):
    __tablename__ = "google_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_google_accounts_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    google_email: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_access_token: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    token_expiry: Mapped[datetime | None] = mapped_column(nullable=True)
    authorized_scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    connected_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user: Mapped["User"] = relationship(back_populates="google_accounts")
