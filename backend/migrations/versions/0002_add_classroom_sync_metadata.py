"""Add classroom sync metadata columns.

Revision ID: 0002_add_classroom_sync_metadata
Revises: 0001_initial_schema
Create Date: 2026-11-03 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "0002_add_classroom_sync_metadata"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("google_accounts", sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("courses", sa.Column("course_state", sa.String(length=50), nullable=True, server_default="ACTIVE"))
    op.add_column("courses", sa.Column("alternate_link", sa.String(length=500), nullable=True))
    op.add_column("assignments", sa.Column("alternate_link", sa.String(length=500), nullable=True))
    op.add_column("assignments", sa.Column("max_points", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("assignments", "max_points")
    op.drop_column("assignments", "alternate_link")
    op.drop_column("courses", "alternate_link")
    op.drop_column("courses", "course_state")
    op.drop_column("google_accounts", "last_synced_at")

