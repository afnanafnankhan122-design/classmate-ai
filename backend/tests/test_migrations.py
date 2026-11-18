import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from alembic import command
from alembic.config import Config

from app.core.config import BACKEND_DIR, settings


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


class MigrationIsolationTests(unittest.TestCase):
    def test_explicit_alembic_url_takes_priority_over_backend_environment(self) -> None:
        with TemporaryDirectory(prefix="classmate-alembic-url-") as directory:
            explicit_database = Path(directory) / "explicit.db"
            environment_database = Path(directory) / "environment.db"
            config = _alembic_config(_sqlite_url(explicit_database))

            with patch.object(settings, "database_url", _sqlite_url(environment_database)):
                command.upgrade(config, "head")

            with closing(sqlite3.connect(explicit_database)) as connection:
                revision = connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()
            self.assertEqual(revision, ("0011_add_legal_acceptance",))
            self.assertFalse(environment_database.exists())

    def test_upgrade_from_device_sessions_preserves_existing_records(self) -> None:
        with TemporaryDirectory(prefix="classmate-alembic-upgrade-") as directory:
            database = Path(directory) / "existing.db"
            environment_database = Path(directory) / "environment.db"
            config = _alembic_config(_sqlite_url(database))

            with patch.object(settings, "database_url", _sqlite_url(environment_database)):
                command.upgrade(config, "0010_add_device_sessions")

            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "INSERT INTO users (full_name, email, created_at) "
                    "VALUES ('Migration Smoke Student', 'migration-smoke@example.com', CURRENT_TIMESTAMP)"
                )
                connection.execute(
                    "INSERT INTO courses (user_id, google_course_id, course_name, is_active, created_at) "
                    "VALUES (1, 'migration-course', 'Preserved Course', 1, CURRENT_TIMESTAMP)"
                )
                connection.execute(
                    "INSERT INTO assignments "
                    "(user_id, course_id, title, status, submission_status, attachments, is_demo, created_at) "
                    "VALUES (1, 1, 'Preserved Assignment', 'assigned', 'not_submitted', '[]', 0, CURRENT_TIMESTAMP)"
                )
                connection.execute(
                    "INSERT INTO google_accounts (user_id, google_sub, google_email, connected_at) "
                    "VALUES (1, 'migration-google-sub', 'migration-smoke@example.com', CURRENT_TIMESTAMP)"
                )
                connection.execute(
                    "INSERT INTO payments "
                    "(user_id, payment_method_id, plan_id, status, amount_paisa, currency, "
                    "duration_months, transaction_reference, transaction_reference_normalized, "
                    "submission_fingerprint) "
                    "VALUES (1, 1, 1, 'pending', 50000, 'PKR', 6, 'MIGRATION-SMOKE', "
                    "'migration-smoke', ?)",
                    ("a" * 64,),
                )
                connection.execute(
                    "INSERT INTO licenses (user_id, plan_id, starts_at, expires_at) "
                    "VALUES (1, 1, '2026-01-01', '2026-07-01')"
                )
                connection.execute(
                    "INSERT INTO device_sessions "
                    "(user_id, device_hash, device_name, created_at, last_activity, expires_at) "
                    "VALUES (1, ?, 'Migration Test Browser', CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP, '2099-01-01')",
                    ("b" * 64,),
                )
                connection.commit()

            with patch.object(settings, "database_url", _sqlite_url(environment_database)):
                command.upgrade(config, "head")

            with closing(sqlite3.connect(database)) as connection:
                preserved = {
                    "user": connection.execute(
                        "SELECT email, terms_version, privacy_policy_version FROM users WHERE id=1"
                    ).fetchone(),
                    "course": connection.execute(
                        "SELECT course_name FROM courses WHERE id=1"
                    ).fetchone(),
                    "assignment": connection.execute(
                        "SELECT title FROM assignments WHERE id=1"
                    ).fetchone(),
                    "google_account": connection.execute(
                        "SELECT google_email FROM google_accounts WHERE id=1"
                    ).fetchone(),
                    "payment": connection.execute(
                        "SELECT transaction_reference FROM payments WHERE id=1"
                    ).fetchone(),
                    "license_count": connection.execute(
                        "SELECT COUNT(*) FROM licenses WHERE user_id=1"
                    ).fetchone(),
                    "device_session": connection.execute(
                        "SELECT device_hash FROM device_sessions WHERE user_id=1"
                    ).fetchone(),
                    "revision": connection.execute(
                        "SELECT version_num FROM alembic_version"
                    ).fetchone(),
                }

            self.assertEqual(
                preserved,
                {
                    "user": ("migration-smoke@example.com", None, None),
                    "course": ("Preserved Course",),
                    "assignment": ("Preserved Assignment",),
                    "google_account": ("migration-smoke@example.com",),
                    "payment": ("MIGRATION-SMOKE",),
                    "license_count": (1,),
                    "device_session": ("b" * 64,),
                    "revision": ("0011_add_legal_acceptance",),
                },
            )
            self.assertFalse(environment_database.exists())


if __name__ == "__main__":
    unittest.main()
