"""Record the assignment version used for each generated document.

Revision ID: 0008_add_assignment_export_history
Revises: 0007_add_assignment_workspace
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_add_assignment_export_history"
down_revision = "0007_add_assignment_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assignment_exports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("draft_version_id", sa.Integer(), nullable=False),
        sa.Column("file_format", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["draft_version_id"],
            ["assignment_draft_versions.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_assignment_exports_assignment_id",
        "assignment_exports",
        ["assignment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_assignment_exports_assignment_id", table_name="assignment_exports")
    op.drop_table("assignment_exports")
