from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, UTC, timedelta
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.core.auth_security import auth_rate_limiter, hash_password
from app.core.config import settings
from app.database.base import Base
from app.database.dependencies import get_db
from app.main import app
from app.models.device_session import DeviceSession
from app.models.user import User
from app.services.google_oauth import OAUTH_SCOPES


class DeviceSessionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_test_marker = os.environ.get("PYTEST_CURRENT_TEST")
        os.environ["PYTEST_CURRENT_TEST"] = "test_device_sessions"
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "device-sessions.sqlite"
        self.engine = create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)

        def override_get_db():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app, base_url="http://localhost:8000")
        self.created_emails: list[str] = []

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
        self.temp_dir.cleanup()
        if self.previous_test_marker is None:
            os.environ.pop("PYTEST_CURRENT_TEST", None)
        else:
            os.environ["PYTEST_CURRENT_TEST"] = self.previous_test_marker
        for email in self.created_emails:
            auth_rate_limiter.reset(f"login:testclient:{email}")

    def create_user(self, email: str, *, is_admin: bool = False) -> User:
        self.created_emails.append(email)
        with Session(self.engine) as db:
            user = User(
                full_name="Device Test Student",
                email=email,
                hashed_password=hash_password("SecureStudent123!"),
                auth_provider="email",
                is_admin=is_admin,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user

    def login(self, client: TestClient, email: str):
        return client.post(
            "/api/auth/login",
            json={"email": email, "password": "SecureStudent123!", "remember_me": False},
        )

    def test_student_login_allows_two_devices_and_blocks_a_third(self) -> None:
        self.create_user("limit@example.com")
        clients = [TestClient(app, base_url="http://localhost:8000") for _ in range(3)]
        try:
            self.assertEqual(self.login(clients[0], "limit@example.com").status_code, 200)
            self.assertEqual(self.login(clients[1], "limit@example.com").status_code, 200)
            blocked = self.login(clients[2], "limit@example.com")

            self.assertEqual(blocked.status_code, 403)
            self.assertEqual(
                blocked.json()["detail"],
                "You have reached your maximum of 2 registered devices. Sign in from an existing device and revoke an old session before registering another device.",
            )
            sessions = clients[0].get("/api/auth/devices").json()
            self.assertEqual(sessions["active_count"], 2)
            self.assertEqual(len([device for device in sessions["devices"] if device["status"] == "active"]), 2)
        finally:
            for client in clients:
                client.close()

    def test_repeated_login_from_same_browser_reuses_device_slot(self) -> None:
        self.create_user("same-device@example.com")
        self.assertEqual(self.login(self.client, "same-device@example.com").status_code, 200)
        self.assertEqual(self.login(self.client, "same-device@example.com").status_code, 200)
        devices = self.client.get("/api/auth/devices").json()
        self.assertEqual(devices["active_count"], 1)
        self.assertEqual(len(devices["devices"]), 1)

    def test_revoke_frees_slot_and_invalidates_the_revoked_session(self) -> None:
        self.create_user("revoke@example.com")
        old_device = TestClient(app, base_url="http://localhost:8000")
        current_device = TestClient(app, base_url="http://localhost:8000")
        new_device = TestClient(app, base_url="http://localhost:8000")
        try:
            self.assertEqual(self.login(old_device, "revoke@example.com").status_code, 200)
            self.assertEqual(self.login(current_device, "revoke@example.com").status_code, 200)
            devices = current_device.get("/api/auth/devices").json()["devices"]
            old_id = next(device["id"] for device in devices if not device["is_current"])
            revoked = current_device.delete(f"/api/auth/devices/{old_id}")
            self.assertEqual(revoked.status_code, 200)
            self.assertFalse(old_device.get("/api/auth/me").json()["authenticated"])
            self.assertEqual(old_device.get("/api/auth/devices").status_code, 401)
            self.assertEqual(self.login(new_device, "revoke@example.com").status_code, 200)
        finally:
            old_device.close()
            current_device.close()
            new_device.close()

    def test_device_ownership_is_enforced_for_listing_and_revocation(self) -> None:
        self.create_user("owner@example.com")
        self.create_user("other-owner@example.com")
        owner = TestClient(app, base_url="http://localhost:8000")
        other = TestClient(app, base_url="http://localhost:8000")
        try:
            self.assertEqual(self.login(owner, "owner@example.com").status_code, 200)
            self.assertEqual(self.login(other, "other-owner@example.com").status_code, 200)
            owner_id = owner.get("/api/auth/devices").json()["devices"][0]["id"]
            other_devices = other.get("/api/auth/devices").json()["devices"]
            self.assertNotIn(owner_id, [device["id"] for device in other_devices])
            self.assertEqual(other.delete(f"/api/auth/devices/{owner_id}").status_code, 404)
            self.assertEqual(owner.get("/api/auth/devices").json()["devices"][0]["status"], "active")
        finally:
            owner.close()
            other.close()

    def test_expired_device_does_not_count_and_logout_revokes_current_session(self) -> None:
        self.create_user("expiry@example.com")
        self.assertEqual(self.login(self.client, "expiry@example.com").status_code, 200)
        with Session(self.engine) as db:
            device = db.scalar(select(DeviceSession))
            self.assertIsNotNone(device)
            db.execute(
                update(DeviceSession)
                .where(DeviceSession.id == device.id)
                .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            db.commit()

        another_device = TestClient(app, base_url="http://localhost:8000")
        try:
            self.assertEqual(self.login(another_device, "expiry@example.com").status_code, 200)
            self.assertEqual(another_device.post("/api/auth/logout").status_code, 200)
            with Session(self.engine) as db:
                active = db.scalars(
                    select(DeviceSession).where(
                        DeviceSession.revoked_at.is_(None),
                        DeviceSession.expires_at > datetime.now(UTC),
                    )
                ).all()
                self.assertEqual(active, [])
        finally:
            another_device.close()

    def test_administrator_accounts_are_not_subject_to_student_device_limit(self) -> None:
        self.create_user("admin-device@example.com", is_admin=True)
        clients = [TestClient(app, base_url="http://localhost:8000") for _ in range(3)]
        try:
            for client in clients:
                self.assertEqual(self.login(client, "admin-device@example.com").status_code, 200)
            self.assertFalse(clients[0].get("/api/auth/devices").json()["policy_applies"])
        finally:
            for client in clients:
                client.close()

    def test_password_change_invalidates_other_device_sessions(self) -> None:
        self.create_user("password-change@example.com")
        other_device = TestClient(app, base_url="http://localhost:8000")
        try:
            self.assertEqual(self.login(self.client, "password-change@example.com").status_code, 200)
            self.assertEqual(self.login(other_device, "password-change@example.com").status_code, 200)
            changed = self.client.post(
                "/api/auth/change-password",
                json={
                    "current_password": "SecureStudent123!",
                    "new_password": "NewSecureStudent456!",
                    "confirm_password": "NewSecureStudent456!",
                },
            )
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(self.client.get("/api/auth/devices").json()["active_count"], 1)
            self.assertEqual(other_device.get("/api/auth/devices").status_code, 401)
        finally:
            other_device.close()

    def test_google_oauth_callback_obeys_student_device_limit(self) -> None:
        self.create_user("google-limit@example.com")
        first_device = TestClient(app, base_url="http://localhost:8000")
        oauth_device = TestClient(app, base_url="http://localhost:8000")
        try:
            self.assertEqual(self.login(self.client, "google-limit@example.com").status_code, 200)
            self.assertEqual(self.login(first_device, "google-limit@example.com").status_code, 200)
            encryption_key = Fernet.generate_key().decode("ascii")
            with (
                patch.object(settings, "google_client_id", "client-id"),
                patch.object(settings, "google_client_secret", "client-secret"),
                patch.object(settings, "google_token_encryption_key", encryption_key),
                patch.object(settings, "google_redirect_uri_lan", ""),
            ):
                start = oauth_device.get("/api/auth/google/start", follow_redirects=False)
                state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
                flow = MagicMock()
                flow.credentials = MagicMock()
                with (
                    patch("app.api.routes.auth.create_oauth_flow", return_value=flow),
                    patch(
                        "app.api.routes.auth.reported_google_scopes",
                        return_value=set(OAUTH_SCOPES),
                    ),
                    patch(
                        "app.api.routes.auth.granted_google_scopes",
                        return_value=set(OAUTH_SCOPES),
                    ),
                    patch(
                        "app.api.routes.auth.get_google_profile",
                        return_value={"email": "google-limit@example.com"},
                    ),
                    patch(
                        "app.api.routes.auth.save_google_login",
                        return_value=self.get_user("google-limit@example.com"),
                    ),
                    patch(
                        "app.api.routes.auth.get_license_status",
                        return_value=MagicMock(active=False),
                    ),
                ):
                    callback = oauth_device.get(
                        "/api/auth/google/callback",
                        params={"state": state, "code": "authorization-code"},
                        follow_redirects=False,
                    )

            self.assertEqual(callback.status_code, 303)
            self.assertIn("google=device_limit", callback.headers["location"])
            self.assertEqual(oauth_device.get("/api/auth/devices").status_code, 401)
        finally:
            first_device.close()
            oauth_device.close()

    def get_user(self, email: str) -> User:
        with Session(self.engine) as db:
            user = db.scalar(select(User).where(User.email == email))
            self.assertIsNotNone(user)
            db.expunge(user)
            return user

    def test_concurrent_new_device_logins_cannot_exceed_limit(self) -> None:
        self.create_user("concurrent@example.com")
        self.assertEqual(self.login(self.client, "concurrent@example.com").status_code, 200)
        barrier = threading.Barrier(2)

        def attempt_login() -> int:
            with TestClient(app, base_url="http://localhost:8000") as client:
                barrier.wait(timeout=5)
                return self.login(client, "concurrent@example.com").status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = sorted(executor.map(lambda _: attempt_login(), range(2)))
        self.assertEqual(statuses, [200, 403])
        self.assertEqual(self.client.get("/api/auth/devices").json()["active_count"], 2)


if __name__ == "__main__":
    unittest.main()
