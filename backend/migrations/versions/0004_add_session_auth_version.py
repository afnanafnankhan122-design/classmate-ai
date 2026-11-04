"""Add per-user session version for global session invalidation.

Revision ID: 0004_add_session_auth_version
Revises: 0003_add_auth_and_notifications
Create Date: 2026-11-04
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_add_session_auth_version"
down_revision = "0003_add_auth_and_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False)
        )

    op.execute(
        "UPDATE password_reset_tokens "
        "SET used_at = CURRENT_TIMESTAMP "
        "WHERE used_at IS NULL"
    )
    op.execute(
        "UPDATE users SET is_verified = CASE WHEN EXISTS ("
        "SELECT 1 FROM google_accounts "
        "WHERE google_accounts.user_id = users.id "
        "AND LOWER(google_accounts.google_email) = LOWER(users.email)"
        ") THEN 1 ELSE 0 END"
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("auth_version")
