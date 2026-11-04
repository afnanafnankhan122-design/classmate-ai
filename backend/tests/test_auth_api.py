import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, settings
from app.database.base import Base
from app.database.dependencies import get_db
from app.main import app
from app.models.google_account import GoogleAccount
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
        with (
            patch.object(settings, "google_client_id", ""),
            patch.object(settings, "google_client_secret", ""),
            patch.object(settings, "google_token_encryption_key", ""),
        ):
            response = self.client.get("/api/auth/google/start")
        self.assertEqual(response.status_code, 503)

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
