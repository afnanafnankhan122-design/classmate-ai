import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, UTC, timedelta
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.config import Settings, settings
from app.core.auth_security import generate_secure_token, hash_token
from app.database.base import Base
from app.database.dependencies import get_db
from app.main import app
from app.models.google_account import GoogleAccount
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User


class AuthApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)

        def override_get_db():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()

    def test_classroom_routes_require_a_signed_in_user(self) -> None:
        response = self.client.get("/api/classroom/courses")
        self.assertEqual(response.status_code, 401)

    def test_google_oauth_start_uses_backend_redirect_and_signed_state(self) -> None:
        encryption_key = Fernet.generate_key().decode("ascii")
        register = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "AUST Student",
                "email": "student@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
            },
        )
        self.assertEqual(register.status_code, 201)
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
        ):
            response = self.client.get("/api/auth/google/start", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        authorization_url = response.headers["location"]
        self.assertIn("accounts.google.com", authorization_url)
        self.assertNotIn("client-secret", authorization_url)
        state = parse_qs(urlparse(authorization_url).query)["state"][0]
        mismatch = self.client.get(
            "/api/auth/google/callback",
            params={"state": "not-the-oauth-state", "code": "not-used"},
            follow_redirects=False,
        )
        self.assertEqual(mismatch.status_code, 400)
        self.assertTrue(state)

    def test_oauth_start_returns_setup_error_when_configuration_is_missing(self) -> None:
        register = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "AUST Student",
                "email": "student@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
            },
        )
        self.assertEqual(register.status_code, 201)
        with (
            patch.object(settings, "google_client_id", ""),
            patch.object(settings, "google_client_secret", ""),
            patch.object(settings, "google_token_encryption_key", ""),
        ):
            response = self.client.get("/api/auth/google/start")
        self.assertEqual(response.status_code, 503)

    def test_registration_cannot_take_over_existing_oauth_only_account(self) -> None:
        with Session(self.engine) as db:
            user = User(
                full_name="Existing Student",
                email="student@example.com",
                hashed_password=None,
                is_verified=True,
            )
            db.add(user)
            db.commit()
            user_id = user.id

        response = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "Attacker",
                "email": "student@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
            },
        )

        self.assertEqual(response.status_code, 409)
        with Session(self.engine) as db:
            existing = db.get(User, user_id)
            self.assertIsNone(existing.hashed_password)
            self.assertEqual(existing.full_name, "Existing Student")

    def test_forgot_password_is_generic_and_never_exposes_a_token(self) -> None:
        with Session(self.engine) as db:
            db.add(User(full_name="Student", email="student@example.com"))
            db.commit()

        response = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "student@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("dev_token", response.json())
        self.assertNotIn("token", response.json())
        with Session(self.engine) as db:
            self.assertEqual(db.query(PasswordResetToken).count(), 0)

    def test_password_reset_invalidates_all_reset_tokens_and_old_sessions(self) -> None:
        register = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "AUST Student",
                "email": "student@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
            },
        )
        self.assertEqual(register.status_code, 201)
        old_cookie = self.client.cookies.get("classmate_session")
        self.assertIsNotNone(old_cookie)

        used_token = generate_secure_token()
        second_token = generate_secure_token()
        with Session(self.engine) as db:
            user = db.scalar(select(User).where(User.email == "student@example.com"))
            db.add_all(
                [
                    PasswordResetToken(
                        user_id=user.id,
                        token_hash=hash_token(used_token),
                        expires_at=datetime.now(UTC) + timedelta(minutes=15),
                    ),
                    PasswordResetToken(
                        user_id=user.id,
                        token_hash=hash_token(second_token),
                        expires_at=datetime.now(UTC) + timedelta(minutes=15),
                    ),
                ]
            )
            db.commit()
            user_id = user.id

        previous_session = TestClient(
            app,
            cookies={"classmate_session": old_cookie},
        )
        try:
            response = self.client.post(
                "/api/auth/reset-password",
                json={
                    "token": used_token,
                    "new_password": "UpdatedStudent456!",
                    "confirm_password": "UpdatedStudent456!",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertFalse(previous_session.get("/api/auth/me").json()["authenticated"])
        finally:
            previous_session.close()

        with Session(self.engine) as db:
            tokens = db.scalars(
                select(PasswordResetToken).where(PasswordResetToken.user_id == user_id)
            ).all()
            self.assertTrue(all(token.used_at is not None for token in tokens))

    def test_untrusted_origin_cannot_submit_state_changing_request(self) -> None:
        response = self.client.post(
            "/api/auth/logout",
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(response.status_code, 403)

    def test_loopback_alias_origin_can_submit_login_preflight(self) -> None:
        response = self.client.options(
            "/api/auth/login",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            "http://127.0.0.1:3000",
        )
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")

        login = self.client.post(
            "/api/auth/login",
            headers={"Origin": "http://127.0.0.1:3000"},
            json={
                "email": "not-registered@example.org",
                "password": "WrongPassword123!",
            },
        )
        self.assertEqual(login.status_code, 401)
        self.assertEqual(
            login.headers["access-control-allow-origin"],
            "http://127.0.0.1:3000",
        )

    def test_callback_handles_user_denied_authorization(self) -> None:
        response = self.client.get(
            "/api/auth/google/callback",
            params={"error": "access_denied"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("google=denied", response.headers["location"])

    def test_me_endpoint_unauthenticated(self) -> None:
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["authenticated"])
        self.assertFalse(data["google_connected"])

    def test_registration_login_and_logout_session_flow(self) -> None:
        registration = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "AUST Student",
                "email": "student@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
            },
        )
        self.assertEqual(registration.status_code, 201)
        set_cookie = registration.headers["set-cookie"].lower()
        self.assertIn("httponly", set_cookie)
        self.assertIn("samesite=lax", set_cookie)
        current = self.client.get("/api/auth/me").json()
        self.assertTrue(current["authenticated"])
        self.assertEqual(current["user"]["email"], "student@example.com")
        self.assertFalse(current["user"]["email_verified"])

        logout = self.client.post("/api/auth/logout")
        self.assertEqual(logout.status_code, 200)
        self.assertFalse(self.client.get("/api/auth/me").json()["authenticated"])

        bad_login = self.client.post(
            "/api/auth/login",
            json={"email": "student@example.com", "password": "WrongPassword123!"},
        )
        self.assertEqual(bad_login.status_code, 401)

        login = self.client.post(
            "/api/auth/login",
            json={
                "email": "STUDENT@example.com",
                "password": "SecureStudent123!",
                "remember_me": False,
            },
        )
        self.assertEqual(login.status_code, 200)
        self.assertTrue(self.client.get("/api/auth/me").json()["authenticated"])

    def test_existing_signed_session_is_upgraded_without_losing_google_access(self) -> None:
        from app.api.routes.auth import _session_user

        with Session(self.engine) as db:
            user = User(full_name="Legacy Student", email="legacy@example.com")
            db.add(user)
            db.commit()
            db.refresh(user)
            user_id = user.id

            request = Request(
                {
                    "type": "http",
                    "session": {"user_id": user_id},
                }
            )
            current_user = _session_user(request, db)

            self.assertEqual(current_user.id, user_id)
            self.assertEqual(request.session["auth_version"], user.auth_version)
            self.assertTrue(request.session["remember_me"])

    def test_disconnect_and_logout_flow(self) -> None:
        from app.api.routes.auth import get_current_user

        with Session(self.engine) as db:
            user = User(full_name="AUST Student", email="student@aust.edu.pk")
            db.add(user)
            db.flush()
            account = GoogleAccount(
                user_id=user.id,
                google_sub="g-123456",
                google_email="student@aust.edu.pk",
                encrypted_access_token="fake-token",
            )
            db.add(account)
            db.commit()
            user_id = user.id

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("app.services.google_oauth.revoke_google_token"):
                res = self.client.post("/api/auth/google/disconnect")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["status"], "disconnected")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        with Session(self.engine) as db:
            remaining = db.scalar(select(GoogleAccount).where(GoogleAccount.user_id == user_id))
            self.assertIsNone(remaining)

    def test_comma_separated_cors_origins_are_accepted(self) -> None:
        configured = Settings(
            _env_file=None,
            backend_cors_origins="http://localhost:3000,http://localhost:3001",
        )
        self.assertEqual(
            configured.backend_cors_origins,
            ["http://localhost:3000", "http://localhost:3001"],
        )

    def test_oauthlib_relax_token_scope_is_active(self) -> None:
        import os
        from oauthlib.oauth2.rfc6749.parameters import validate_token_parameters

        self.assertEqual(os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE"), "1")
        # Ensure a simulated Google scope change does not raise Warning
        mock_params = type(
            "MockParams",
            (),
            {
                "scope_changed": True,
                "old_scope": "scopeA",
                "scope": "scopeB",
                "old_scopes": ["scopeA"],
                "scopes": ["scopeB"],
                "get": lambda self, k: None,
                "__contains__": lambda self, k: k == "access_token",
            },
        )()
        # Should execute cleanly without raising Warning
        validate_token_parameters(mock_params)


if __name__ == "__main__":
    unittest.main()
