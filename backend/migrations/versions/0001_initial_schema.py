"""Create the initial ClassMate AI schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("roll_number", sa.String(length=100), nullable=True),
        sa.Column("department", sa.String(length=150), nullable=True),
        sa.Column("semester", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "google_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("google_sub", sa.String(length=255), nullable=False),
        sa.Column("google_email", sa.String(length=255), nullable=False),
        sa.Column("encrypted_access_token", sa.String(length=2000), nullable=True),
        sa.Column("encrypted_refresh_token", sa.String(length=2000), nullable=True),
        sa.Column("token_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_google_accounts_user_id"),
    )
    op.create_index("ix_google_accounts_id", "google_accounts", ["id"])
    op.create_index("ix_google_accounts_google_sub", "google_accounts", ["google_sub"], unique=True)

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("google_course_id", sa.String(length=255), nullable=False),
        sa.Column("course_name", sa.String(length=255), nullable=False),
        sa.Column("course_section", sa.String(length=150), nullable=True),
        sa.Column("time_zone", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "google_course_id", name="uq_course_user_google_id"),
    )
    op.create_index("ix_courses_id", "courses", ["id"])
    op.create_index("ix_courses_google_course_id", "courses", ["google_course_id"])

    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=True),
        sa.Column("google_assignment_id", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_time", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("submission_status", sa.String(length=50), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "course_id",
            "google_assignment_id",
            name="uq_assignment_course_google_id",
        ),
    )
    op.create_index("ix_assignments_id", "assignments", ["id"])
    op.create_index(
        "ix_assignments_google_assignment_id",
        "assignments",
        ["google_assignment_id"],
    )

    op.create_table(
        "assignment_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("original_file", sa.String(length=500), nullable=True),
        sa.Column("generated_pdf", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assignment_documents_id", "assignment_documents", ["id"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("approval_status", sa.String(length=50), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_approvals_id", "approvals", ["id"])

    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("google_submission_id", sa.String(length=255), nullable=True),
        sa.Column("submission_status", sa.String(length=50), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_submissions_id", "submissions", ["id"])

    op.create_table(
        "ai_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_activity_id", "ai_activity", ["id"])


def downgrade() -> None:
    op.drop_table("ai_activity")
    op.drop_index("ix_submissions_id", table_name="submissions")
    op.drop_table("submissions")
    op.drop_index("ix_approvals_id", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_assignment_documents_id", table_name="assignment_documents")
    op.drop_table("assignment_documents")
    op.drop_index("ix_assignments_google_assignment_id", table_name="assignments")
    op.drop_index("ix_assignments_id", table_name="assignments")
    op.drop_table("assignments")
    op.drop_index("ix_courses_google_course_id", table_name="courses")
    op.drop_index("ix_courses_id", table_name="courses")
    op.drop_table("courses")
    op.drop_index("ix_google_accounts_google_sub", table_name="google_accounts")
    op.drop_index("ix_google_accounts_id", table_name="google_accounts")
    op.drop_table("google_accounts")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
