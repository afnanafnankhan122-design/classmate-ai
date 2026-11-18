"""Add google_id and auth_provider to users.

Revision ID: 0005_add_google_id_and_auth_provider
Revises: 0004_add_session_auth_version
Create Date: 2026-11-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_add_google_id_and_auth_provider"
down_revision = "0004_add_session_auth_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("google_id", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "auth_provider",
                sa.String(length=50),
                server_default="email",
                nullable=False,
            )
        )
    op.create_index("ix_users_google_id", "users", ["google_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_google_id", table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("auth_provider")
        batch_op.drop_column("google_id")
