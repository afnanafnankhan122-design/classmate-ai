"""Add semester payment and licensing tables.

Revision ID: 0006_add_semester_licensing
Revises: 0005_add_google_id_and_auth_provider
Create Date: 2026-11-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_add_semester_licensing"
down_revision = "0005_add_google_id_and_auth_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False)
        )

    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("amount_paisa", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="PKR", nullable=False),
        sa.Column("duration_months", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint("amount_paisa > 0", name="ck_plan_amount_positive"),
        sa.CheckConstraint("duration_months > 0", name="ck_plan_duration_positive"),
    )
    op.create_table(
        "licensing_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("launch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grandfathering_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("configured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("configured_by_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_licensing_policy_singleton"),
        sa.CheckConstraint(
            "grandfathering_days BETWEEN 1 AND 365",
            name="ck_licensing_policy_grandfathering_days",
        ),
        sa.ForeignKeyConstraint(
            ["configured_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_table(
        "payment_methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("account_holder_name", sa.String(length=255), nullable=True),
        sa.Column("account_number", sa.String(length=100), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("details_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details_verified_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "is_enabled = false OR "
            "(account_holder_name IS NOT NULL AND length(trim(account_holder_name)) > 0 AND "
            "account_number IS NOT NULL AND length(trim(account_number)) > 0 AND "
            "instructions IS NOT NULL AND length(trim(instructions)) > 0 AND "
            "details_verified_at IS NOT NULL AND details_verified_by_user_id IS NOT NULL)",
            name="ck_payment_method_enabled_verified",
        ),
        sa.ForeignKeyConstraint(
            ["details_verified_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_payment_method_enabled", "payment_methods", ["is_enabled"])
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("payment_method_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("amount_paisa", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("duration_months", sa.Integer(), nullable=False),
        sa.Column("transaction_reference", sa.String(length=128), nullable=False),
        sa.Column("transaction_reference_normalized", sa.String(length=128), nullable=False),
        sa.Column("receipt_storage_key", sa.String(length=64), nullable=True, unique=True),
        sa.Column("receipt_content_type", sa.String(length=32), nullable=True),
        sa.Column("receipt_size", sa.Integer(), nullable=True),
        sa.Column("receipt_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("submission_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("resubmission_of_id", sa.Integer(), nullable=True),
        sa.Column("license_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("license_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("refund_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_payment_status",
        ),
        sa.CheckConstraint("amount_paisa > 0", name="ck_payment_amount_positive"),
        sa.CheckConstraint("duration_months > 0", name="ck_payment_duration_positive"),
        sa.CheckConstraint(
            "length(trim(transaction_reference)) > 0 AND "
            "length(trim(transaction_reference_normalized)) > 0",
            name="ck_payment_reference_nonempty",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND reviewed_at IS NULL AND reviewed_by_user_id IS NULL "
            "AND rejection_reason IS NULL) OR "
            "(status = 'approved' AND reviewed_at IS NOT NULL AND reviewed_by_user_id IS NOT NULL "
            "AND rejection_reason IS NULL) OR "
            "(status = 'rejected' AND reviewed_at IS NOT NULL AND reviewed_by_user_id IS NOT NULL "
            "AND rejection_reason IS NOT NULL AND length(trim(rejection_reason)) > 0)",
            name="ck_payment_review_state",
        ),
        sa.CheckConstraint(
            "(refunded_at IS NULL AND refunded_by_user_id IS NULL AND refund_reason IS NULL) OR "
            "(status = 'approved' AND refunded_at IS NOT NULL AND refunded_by_user_id IS NOT NULL "
            "AND refund_reason IS NOT NULL AND length(trim(refund_reason)) > 0)",
            name="ck_payment_refund_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["payment_method_id"],
            ["payment_methods.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["resubmission_of_id"],
            ["payments.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["refunded_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "payment_method_id",
            "transaction_reference_normalized",
            name="uq_payment_method_reference",
        ),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_payment_user_idempotency",
        ),
    )
    op.create_index(
        "uq_payment_one_pending_per_user",
        "payments",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_payment_status_submitted_at",
        "payments",
        ["status", "submitted_at"],
    )
    op.create_index(
        "ix_payment_user_submitted_at",
        "payments",
        ["user_id", "submitted_at"],
    )
    op.create_index("ix_payment_refunded_at", "payments", ["refunded_at"])
    op.create_table(
        "licenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("last_approved_payment_id", sa.Integer(), nullable=True, unique=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("expires_at > starts_at", name="ck_license_expiry_after_start"),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL "
            "AND revocation_reason IS NOT NULL AND length(trim(revocation_reason)) > 0)",
            name="ck_license_revocation_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["last_approved_payment_id"],
            ["payments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("user_id", name="uq_license_user"),
    )
    op.create_index("ix_license_expires_at", "licenses", ["expires_at"])
    op.create_table(
        "license_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("license_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["license_id"], ["licenses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_license_audit_user_created_at",
        "license_audit_logs",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_license_audit_payment_created_at",
        "license_audit_logs",
        ["payment_id", "created_at"],
    )

    plans = sa.table(
        "plans",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("amount_paisa", sa.Integer()),
        sa.column("currency", sa.String()),
        sa.column("duration_months", sa.Integer()),
        sa.column("is_enabled", sa.Boolean()),
    )
    op.bulk_insert(
        plans,
        [
            {
                "id": 1,
                "code": "semester",
                "name": "Semester",
                "amount_paisa": 50000,
                "currency": "PKR",
                "duration_months": 6,
                "is_enabled": True,
            }
        ],
    )
    methods = sa.table(
        "payment_methods",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("is_enabled", sa.Boolean()),
    )
    op.bulk_insert(
        methods,
        [
            {"id": 1, "code": "easypaisa", "name": "Easypaisa", "is_enabled": False},
            {"id": 2, "code": "jazzcash", "name": "JazzCash", "is_enabled": False},
            {"id": 3, "code": "bank_transfer", "name": "Bank transfer", "is_enabled": False},
        ],
    )
    policy = sa.table(
        "licensing_policy",
        sa.column("id", sa.Integer()),
        sa.column("grandfathering_days", sa.Integer()),
    )
    op.bulk_insert(policy, [{"id": 1, "grandfathering_days": 30}])


def downgrade() -> None:
    op.drop_index("ix_license_audit_payment_created_at", table_name="license_audit_logs")
    op.drop_index("ix_license_audit_user_created_at", table_name="license_audit_logs")
    op.drop_table("license_audit_logs")
    op.drop_index("ix_license_expires_at", table_name="licenses")
    op.drop_table("licenses")
    op.drop_index("ix_payment_user_submitted_at", table_name="payments")
    op.drop_index("ix_payment_status_submitted_at", table_name="payments")
    op.drop_index("ix_payment_refunded_at", table_name="payments")
    op.drop_index("uq_payment_one_pending_per_user", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_payment_method_enabled", table_name="payment_methods")
    op.drop_table("payment_methods")
    op.drop_table("licensing_policy")
    op.drop_table("plans")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_admin")
