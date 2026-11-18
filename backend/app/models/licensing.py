from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("amount_paisa > 0", name="ck_plan_amount_positive"),
        CheckConstraint("duration_months > 0", name="ck_plan_duration_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount_paisa: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="PKR", server_default="PKR")
    duration_months: Mapped[int] = mapped_column(Integer, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


class LicensingPolicy(Base):
    __tablename__ = "licensing_policy"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_licensing_policy_singleton"),
        CheckConstraint(
            "grandfathering_days BETWEEN 1 AND 365",
            name="ck_licensing_policy_grandfathering_days",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    launch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grandfathering_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    configured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    configured_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class PaymentMethod(Base):
    __tablename__ = "payment_methods"
    __table_args__ = (
        Index("ix_payment_method_enabled", "is_enabled"),
        CheckConstraint(
            "is_enabled = false OR "
            "(account_holder_name IS NOT NULL AND length(trim(account_holder_name)) > 0 AND "
            "account_number IS NOT NULL AND length(trim(account_number)) > 0 AND "
            "instructions IS NOT NULL AND length(trim(instructions)) > 0 AND "
            "details_verified_at IS NOT NULL AND "
            "details_verified_by_user_id IS NOT NULL)",
            name="ck_payment_method_enabled_verified",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_holder_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    details_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details_verified_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    details_verified_by = relationship("User", foreign_keys=[details_verified_by_user_id])


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_payment_status",
        ),
        CheckConstraint("amount_paisa > 0", name="ck_payment_amount_positive"),
        CheckConstraint("duration_months > 0", name="ck_payment_duration_positive"),
        CheckConstraint(
            "length(trim(transaction_reference)) > 0 AND "
            "length(trim(transaction_reference_normalized)) > 0",
            name="ck_payment_reference_nonempty",
        ),
        CheckConstraint(
            "(status = 'pending' AND reviewed_at IS NULL AND reviewed_by_user_id IS NULL "
            "AND rejection_reason IS NULL) OR "
            "(status = 'approved' AND reviewed_at IS NOT NULL AND reviewed_by_user_id IS NOT NULL "
            "AND rejection_reason IS NULL) OR "
            "(status = 'rejected' AND reviewed_at IS NOT NULL AND reviewed_by_user_id IS NOT NULL "
            "AND rejection_reason IS NOT NULL AND length(trim(rejection_reason)) > 0)",
            name="ck_payment_review_state",
        ),
        CheckConstraint(
            "(refunded_at IS NULL AND refunded_by_user_id IS NULL AND refund_reason IS NULL) OR "
            "(status = 'approved' AND refunded_at IS NOT NULL AND refunded_by_user_id IS NOT NULL "
            "AND refund_reason IS NOT NULL AND length(trim(refund_reason)) > 0)",
            name="ck_payment_refund_state",
        ),
        UniqueConstraint(
            "payment_method_id",
            "transaction_reference_normalized",
            name="uq_payment_method_reference",
        ),
        UniqueConstraint("user_id", "idempotency_key", name="uq_payment_user_idempotency"),
        Index(
            "uq_payment_one_pending_per_user",
            "user_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_payment_status_submitted_at", "status", "submitted_at"),
        Index("ix_payment_user_submitted_at", "user_id", "submitted_at"),
        Index("ix_payment_refunded_at", "refunded_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    payment_method_id: Mapped[int] = mapped_column(
        ForeignKey("payment_methods.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    amount_paisa: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    duration_months: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    transaction_reference_normalized: Mapped[str] = mapped_column(String(128), nullable=False)
    receipt_storage_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    receipt_content_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    receipt_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receipt_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submission_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    resubmission_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    license_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    license_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    refund_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    payment_method = relationship("PaymentMethod")
    plan = relationship("Plan")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_user_id])
    refunded_by = relationship("User", foreign_keys=[refunded_by_user_id])
    resubmission_of = relationship("Payment", remote_side="Payment.id")


class License(Base):
    __tablename__ = "licenses"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_license_user"),
        CheckConstraint("expires_at > starts_at", name="ck_license_expiry_after_start"),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL "
            "AND revocation_reason IS NOT NULL AND length(trim(revocation_reason)) > 0)",
            name="ck_license_revocation_state",
        ),
        Index("ix_license_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False)
    last_approved_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"),
        unique=True,
        nullable=True,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    user = relationship("User", foreign_keys=[user_id])
    plan = relationship("Plan")
    last_approved_payment = relationship("Payment")
    revoked_by = relationship("User", foreign_keys=[revoked_by_user_id])


class LicenseAuditLog(Base):
    __tablename__ = "license_audit_logs"
    __table_args__ = (
        Index("ix_license_audit_user_created_at", "user_id", "created_at"),
        Index("ix_license_audit_payment_created_at", "payment_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)
    license_id: Mapped[int | None] = mapped_column(ForeignKey("licenses.id", ondelete="SET NULL"), nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    details: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    user = relationship("User", foreign_keys=[user_id])
    payment = relationship("Payment")
    license = relationship("License")
    actor = relationship("User", foreign_keys=[actor_user_id])
