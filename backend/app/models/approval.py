from datetime import datetime, UTC

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    document_version: Mapped[int] = mapped_column(nullable=False, default=1)
    approval_status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    assignment: Mapped["Assignment"] = relationship(back_populates="approvals")
