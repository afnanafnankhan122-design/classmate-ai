"""Add editable assignment drafts and version history.

Revision ID: 0007_add_assignment_workspace
Revises: 0006_add_semester_licensing
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_add_assignment_workspace"
down_revision = "0006_add_semester_licensing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.add_column(sa.Column("draft_content", sa.Text(), nullable=True))

    op.create_table(
        "assignment_draft_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("assignment_id", "version", name="uq_assignment_draft_version"),
    )
    op.create_index(
        "ix_assignment_draft_versions_assignment_id",
        "assignment_draft_versions",
        ["assignment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_assignment_draft_versions_assignment_id", table_name="assignment_draft_versions")
    op.drop_table("assignment_draft_versions")
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.drop_column("draft_content")
