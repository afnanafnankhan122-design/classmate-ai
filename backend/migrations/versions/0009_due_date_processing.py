"""Persist due-date processing, approval workflow, OAuth scopes, and exported PDFs.

Revision ID: 0009_due_date_processing
Revises: 0008_add_assignment_export_history
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_due_date_processing"
down_revision = "0008_add_assignment_export_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("processing_status", sa.String(length=50), server_default="pending", nullable=False),
    )
    op.add_column(
        "assignments",
        sa.Column("processing_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("assignments", sa.Column("processing_started_at", sa.DateTime(timezone=True)))
    op.add_column("assignments", sa.Column("processing_claim_id", sa.String(length=64)))
    op.add_column("assignments", sa.Column("processing_next_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("assignments", sa.Column("processing_error", sa.String(length=500)))
    op.add_column("assignments", sa.Column("processed_at", sa.DateTime(timezone=True)))
    op.add_column("assignment_exports", sa.Column("file_content", sa.LargeBinary()))
    op.add_column(
        "google_accounts",
        sa.Column("authorized_scopes", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "submissions",
        sa.Column("google_file_id", sa.String(length=255)),
    )
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.add_column(sa.Column("draft_version_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_submissions_draft_version_id_assignment_draft_versions",
            "assignment_draft_versions",
            ["draft_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.add_column(sa.Column("assignment_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_notifications_assignment_id", ["assignment_id"])
        batch_op.create_foreign_key(
            "fk_notifications_assignment_id_assignments",
            "assignments",
            ["assignment_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.drop_constraint(
            "fk_notifications_assignment_id_assignments",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_notifications_assignment_id")
        batch_op.drop_column("assignment_id")
    with op.batch_alter_table("submissions") as batch_op:
        batch_op.drop_constraint(
            "fk_submissions_draft_version_id_assignment_draft_versions",
            type_="foreignkey",
        )
        batch_op.drop_column("draft_version_id")
    op.drop_column("submissions", "google_file_id")
    op.drop_column("google_accounts", "authorized_scopes")
    op.drop_column("assignment_exports", "file_content")
    op.drop_column("assignments", "processed_at")
    op.drop_column("assignments", "processing_error")
    op.drop_column("assignments", "processing_next_attempt_at")
    op.drop_column("assignments", "processing_started_at")
    op.drop_column("assignments", "processing_claim_id")
    op.drop_column("assignments", "processing_attempts")
    op.drop_column("assignments", "processing_status")
