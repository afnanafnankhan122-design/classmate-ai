"""Record versioned Terms and Privacy acceptance at registration.

Revision ID: 0011_add_legal_acceptance
Revises: 0010_add_device_sessions
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_add_legal_acceptance"
down_revision = "0010_add_device_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("terms_version", sa.String(length=50), nullable=True))
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("privacy_policy_version", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("privacy_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "privacy_acknowledged_at")
    op.drop_column("users", "privacy_policy_version")
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "terms_version")
