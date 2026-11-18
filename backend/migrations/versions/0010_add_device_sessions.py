"""Persist device-bound authentication sessions.

Revision ID: 0010_add_device_sessions
Revises: 0009_due_date_processing
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_add_device_sessions"
down_revision = "0009_due_date_processing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_hash", sa.String(length=64), nullable=False),
        sa.Column("device_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "device_hash", name="uq_device_sessions_user_device"),
    )
    op.create_index("ix_device_sessions_id", "device_sessions", ["id"])
    op.create_index("ix_device_sessions_user_id", "device_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_device_sessions_user_id", table_name="device_sessions")
    op.drop_index("ix_device_sessions_id", table_name="device_sessions")
    op.drop_table("device_sessions")
