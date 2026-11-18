import base64
import hashlib
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, UTC, timedelta
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.config import Settings, settings
from app.core.auth_security import auth_rate_limiter, generate_secure_token, hash_token
from app.database.base import Base
from app.database.dependencies import get_db
from app.main import app
from app.models.google_account import GoogleAccount
from app.models.licensing import License, LicensingPolicy, Plan
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.services.google_oauth import OAUTH_SCOPES


class AuthApiTests(unittest.TestCase):
    def setUp(self) -> None:
        for endpoint in ("register", "forgot", "reset"):
            auth_rate_limiter.reset(f"{endpoint}:testclient")
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
        self.client = TestClient(app, base_url="http://localhost:8000")

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        for endpoint in ("register", "forgot", "reset"):
            auth_rate_limiter.reset(f"{endpoint}:testclient")
        self.client.close()
        self.engine.dispose()

    @staticmethod
    def smtp_settings_patch():
        return patch.multiple(
            settings,
            smtp_host="smtp.example.test",
            smtp_port=587,
            smtp_username="classmate@example.test",
            smtp_password="smtp-secret-for-tests",
            smtp_from_email="no-reply@example.test",
            smtp_from_name="ClassMate AI",
            smtp_use_ssl=False,
            smtp_starttls=True,
        )

    @staticmethod
    def smtp_unconfigured_patch():
        return patch.multiple(
            settings,
            smtp_host="",
            smtp_username="",
            smtp_password="",
            smtp_from_email="",
            smtp_use_ssl=False,
            smtp_starttls=False,
        )

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
                "terms_accepted": True,
            },
        )
        self.assertEqual(register.status_code, 201)
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
            patch.object(settings, "google_redirect_uri_lan", ""),
        ):
            response = self.client.get("/api/auth/google/start", follow_redirects=False)
            loopback_response = self.client.get(
                "/api/auth/google/start",
                headers={"host": "127.0.0.1:8000"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        authorization_url = response.headers["location"]
        self.assertIn("accounts.google.com", authorization_url)
        self.assertNotIn("client-secret", authorization_url)
        authorization_params = parse_qs(urlparse(authorization_url).query)
        self.assertEqual(authorization_params["redirect_uri"][0], settings.google_redirect_uri)
        requested_scopes = set(authorization_params["scope"][0].split())
        self.assertEqual(requested_scopes, set(OAUTH_SCOPES))
        self.assertFalse(any(".students" in scope for scope in requested_scopes))
        self.assertFalse(any("student-submissions" in scope for scope in requested_scopes))
        self.assertIn("https://www.googleapis.com/auth/classroom.coursework.me", requested_scopes)
        self.assertNotIn(
            "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
            requested_scopes,
        )
        self.assertIn("https://www.googleapis.com/auth/drive.file", requested_scopes)
        self.assertEqual(authorization_params["include_granted_scopes"], ["true"])
        self.assertEqual(authorization_params["prompt"], ["consent"])
        self.assertEqual(authorization_params["code_challenge_method"], ["S256"])
        self.assertEqual(len(authorization_params["code_challenge"][0]), 43)
        self.assertEqual(loopback_response.status_code, 302)
        self.assertEqual(
            parse_qs(urlparse(loopback_response.headers["location"]).query)["redirect_uri"][0],
            settings.google_redirect_uri,
        )
        state = parse_qs(urlparse(authorization_url).query)["state"][0]
        mismatch = self.client.get(
            "/api/auth/google/callback",
            params={"state": "not-the-oauth-state", "code": "not-used"},
            follow_redirects=False,
        )
        self.assertEqual(mismatch.status_code, 400)
        self.assertTrue(state)

    def test_google_oauth_start_rejects_lan_host_without_matching_callback(self) -> None:
        lan_callback = (
            "https://swimming-heavy-legislature-obtaining.trycloudflare.com"
            "/api/auth/google/callback"
        )
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_redirect_uri_lan", lan_callback),
            patch.object(
                settings,
                "backend_cors_origins",
                ["http://localhost:3000", "http://192.168.1.9:3000"],
            ),
        ):
            response = self.client.get(
                "/api/auth/google/start",
                headers={"host": "192.168.1.9:8000"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)

    def test_google_oauth_start_uses_trusted_frontend_host_for_callback(self) -> None:
        encryption_key = Fernet.generate_key().decode("ascii")
        cloudflare_host = "swimming-heavy-legislature-obtaining.trycloudflare.com"
        lan_callback = f"https://{cloudflare_host}/api/auth/google/callback"
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
            patch.object(settings, "google_redirect_uri_lan", lan_callback),
            patch.object(
                settings,
                "backend_cors_origins",
                ["http://localhost:3000", f"https://{cloudflare_host}"],
            ),
        ):
            client = TestClient(app, base_url=f"https://{cloudflare_host}")
            try:
                response = client.get(
                    "/api/auth/google/start",
                    headers={
                        "host": "localhost:8000",
                        "x-forwarded-host": "localhost:8000",
                        "referer": f"https://{cloudflare_host}/",
                    },
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 302)
                set_cookie = response.headers["set-cookie"].lower()
                self.assertIn("httponly", set_cookie)
                self.assertIn("samesite=lax", set_cookie)
                self.assertIn("path=/", set_cookie)
                self.assertNotIn("domain=", set_cookie)
                authorization_params = parse_qs(urlparse(response.headers["location"]).query)
                self.assertEqual(authorization_params["redirect_uri"][0], lan_callback)
                self.assertEqual(authorization_params["code_challenge_method"], ["S256"])
                callback = client.get(
                    "/api/auth/google/callback",
                    params={
                        "error": "access_denied",
                        "state": authorization_params["state"][0],
                    },
                    follow_redirects=False,
                )
            finally:
                client.close()

        self.assertEqual(
            callback.headers["location"],
            f"https://{cloudflare_host}?google=denied",
        )

    def test_google_callback_uses_pkce_verifier_saved_at_start(self) -> None:
        encryption_key = Fernet.generate_key().decode("ascii")
        register = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "AUST Student",
                "email": "pkce@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
                "terms_accepted": True,
            },
        )
        self.assertEqual(register.status_code, 201)
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
            patch.object(settings, "google_redirect_uri_lan", ""),
        ):
            start = self.client.get("/api/auth/google/start", follow_redirects=False)
            authorization_params = parse_qs(urlparse(start.headers["location"]).query)
            with Session(self.engine) as db:
                user = db.get(User, register.json()["user"]["id"])
            flow = MagicMock()
            flow.credentials = MagicMock()
            flow.credentials.granted_scopes = list(OAUTH_SCOPES)
            flow.credentials.scopes = list(OAUTH_SCOPES)
            flow.credentials.token = "oauth-secret-token"
            with (
                patch("app.api.routes.auth.create_oauth_flow", return_value=flow) as create_flow,
                patch(
                    "app.api.routes.auth.get_google_profile",
                    return_value={"email": "pkce@example.com"},
                ),
                patch("app.api.routes.auth.save_google_login", return_value=user),
                patch(
                    "app.api.routes.auth.get_license_status",
                    return_value=MagicMock(active=False),
                ),
                self.assertLogs("app.api.routes.auth", level="INFO") as scope_logs,
            ):
                callback = self.client.get(
                    "/api/auth/google/callback",
                    params={
                        "state": authorization_params["state"][0],
                        "code": "authorization-code",
                    },
                    follow_redirects=False,
                )

        self.assertEqual(callback.status_code, 303)
        output = "\n".join(scope_logs.output)
        self.assertIn("Google scopes requested", output)
        self.assertIn("Google scopes returned by token endpoint", output)
        self.assertNotIn(
            "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
            output,
        )
        self.assertNotIn("oauth-secret-token", output)
        verifier = create_flow.call_args.kwargs["code_verifier"]
        expected_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        self.assertEqual(authorization_params["code_challenge"][0], expected_challenge)

    def test_google_oauth_start_rejects_unconfigured_host(self) -> None:
        encryption_key = Fernet.generate_key().decode("ascii")
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
            patch.object(
                settings,
                "google_redirect_uri_lan",
                "https://classmate.example/api/auth/google/callback",
            ),
            patch.object(
                settings,
                "backend_cors_origins",
                ["http://localhost:3000", "http://192.168.1.9:3000"],
            ),
        ):
            response = self.client.get(
                "/api/auth/google/start",
                headers={"host": "unconfigured.example"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)

    def test_oauth_start_returns_setup_error_when_configuration_is_missing(self) -> None:
        register = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "AUST Student",
                "email": "student@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
                "terms_accepted": True,
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
                "terms_accepted": True,
            },
        )

        self.assertEqual(response.status_code, 409)
        with Session(self.engine) as db:
            existing = db.get(User, user_id)
            self.assertIsNone(existing.hashed_password)
            self.assertEqual(existing.full_name, "Existing Student")

    def test_registration_requires_terms_and_privacy_acceptance(self) -> None:
        payload = {
            "full_name": "Consent Student",
            "email": "consent@example.com",
            "password": "SecureStudent123!",
            "confirm_password": "SecureStudent123!",
        }
        missing = self.client.post("/api/auth/register", json=payload)
        declined = self.client.post(
            "/api/auth/register",
            json={**payload, "terms_accepted": False},
        )

        self.assertEqual(missing.status_code, 422)
        self.assertEqual(declined.status_code, 400)
        with Session(self.engine) as db:
            self.assertIsNone(
                db.scalar(select(User).where(User.email == "consent@example.com"))
            )

    def test_registration_records_server_selected_legal_versions_and_timestamps(self) -> None:
        from app.api.routes.auth import PRIVACY_POLICY_VERSION, TERMS_VERSION

        response = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "Consent Student",
                "email": "consent@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
                "terms_accepted": True,
            },
        )

        self.assertEqual(response.status_code, 201)
        with Session(self.engine) as db:
            user = db.scalar(select(User).where(User.email == "consent@example.com"))
            self.assertEqual(user.terms_version, TERMS_VERSION)
            self.assertEqual(user.privacy_policy_version, PRIVACY_POLICY_VERSION)
            self.assertIsNotNone(user.terms_accepted_at)
            self.assertIsNotNone(user.privacy_acknowledged_at)
            terms_time = user.terms_accepted_at
            privacy_time = user.privacy_acknowledged_at
            if terms_time.tzinfo is None:
                terms_time = terms_time.replace(tzinfo=UTC)
            if privacy_time.tzinfo is None:
                privacy_time = privacy_time.replace(tzinfo=UTC)
            self.assertEqual(terms_time, privacy_time)
            self.assertLessEqual(abs((datetime.now(UTC) - terms_time).total_seconds()), 5)

    def test_registration_rejects_client_supplied_consent_metadata(self) -> None:
        response = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "Consent Student",
                "email": "consent@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
                "terms_accepted": True,
                "terms_version": "forged-version",
                "terms_accepted_at": "2000-01-01T00:00:00Z",
                "privacy_policy_version": "forged-version",
                "privacy_acknowledged_at": "2000-01-01T00:00:00Z",
            },
        )

        self.assertEqual(response.status_code, 422)
        with Session(self.engine) as db:
            self.assertIsNone(
                db.scalar(select(User).where(User.email == "consent@example.com"))
            )

    def test_forgot_password_response_is_generic_without_email_configuration(self) -> None:
        with Session(self.engine) as db:
            db.add(
                User(
                    full_name="Student",
                    email="student@example.com",
                    hashed_password="existing-password-hash",
                )
            )
            db.commit()

        with patch("app.api.routes.auth.send_password_reset_email") as send_email:
            with self.smtp_unconfigured_patch():
                existing_response = self.client.post(
                    "/api/auth/forgot-password",
                    json={"email": "student@example.com"},
                )
                missing_response = self.client.post(
                    "/api/auth/forgot-password",
                    json={"email": "nobody@example.com"},
                )

        self.assertEqual(existing_response.status_code, 200)
        self.assertEqual(existing_response.json(), missing_response.json())
        self.assertFalse(existing_response.json()["email_delivery_configured"])
        with Session(self.engine) as db:
            self.assertEqual(db.query(PasswordResetToken).count(), 0)
        send_email.assert_not_called()

    def test_existing_password_account_gets_email_with_hashed_expiring_token(self) -> None:
        with Session(self.engine) as db:
            user = User(
                full_name="Student",
                email="student@example.com",
                hashed_password="existing-password-hash",
            )
            db.add(user)
            db.commit()
            user_id = user.id

        with self.smtp_settings_patch(), patch(
            "app.api.routes.auth.send_password_reset_email"
        ) as send_email:
            response = self.client.post(
                "/api/auth/forgot-password",
                json={"email": "STUDENT@example.com"},
                headers={"host": "attacker.example"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["email_delivery_configured"])
        send_email.assert_called_once()
        recipient, reset_url, expiration_minutes = send_email.call_args.args
        token = parse_qs(urlparse(reset_url).fragment)["reset_token"][0]
        self.assertEqual(recipient, "student@example.com")
        self.assertTrue(reset_url.startswith(settings.frontend_url))
        self.assertNotIn("attacker.example", reset_url)
        self.assertEqual(expiration_minutes, 30)
        with Session(self.engine) as db:
            token_record = db.scalar(
                select(PasswordResetToken).where(
                    PasswordResetToken.user_id == user_id,
                )
            )
            self.assertIsNotNone(token_record)
            self.assertEqual(token_record.token_hash, hash_token(token))
            self.assertNotEqual(token_record.token_hash, token)
            expiration = token_record.expires_at
            if expiration.tzinfo is None:
                expiration = expiration.replace(tzinfo=UTC)
            self.assertAlmostEqual(
                (expiration - datetime.now(UTC)).total_seconds(),
                30 * 60,
                delta=10,
            )

    def test_google_only_account_does_not_get_local_reset_token_or_email(self) -> None:
        with Session(self.engine) as db:
            db.add(
                User(
                    full_name="Google Student",
                    email="google@example.com",
                    hashed_password=None,
                    auth_provider="google",
                )
            )
            db.commit()

        with self.smtp_settings_patch(), patch(
            "app.api.routes.auth.send_password_reset_email"
        ) as send_email:
            response = self.client.post(
                "/api/auth/forgot-password",
                json={"email": "google@example.com"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Google Sign-In", response.json()["message"])
        self.assertTrue(response.json()["email_delivery_configured"])
        send_email.assert_not_called()
        with Session(self.engine) as db:
            self.assertEqual(db.query(PasswordResetToken).count(), 0)

    def test_reset_email_delivery_failure_does_not_log_token_or_password(self) -> None:
        with Session(self.engine) as db:
            db.add(
                User(
                    full_name="Student",
                    email="student@example.com",
                    hashed_password="existing-password-hash",
                )
            )
            db.commit()

        sent_values: dict[str, str] = {}

        def fail_delivery(recipient: str, reset_url: str, expires: int) -> None:
            self.assertEqual(recipient, "student@example.com")
            self.assertEqual(expires, 30)
            sent_values["token"] = parse_qs(urlparse(reset_url).fragment)["reset_token"][0]
            raise RuntimeError(f"{sent_values['token']} NeverLogThisPassword123!")

        with (
            self.smtp_settings_patch(),
            patch(
                "app.api.routes.auth.send_password_reset_email",
                side_effect=fail_delivery,
            ),
            self.assertLogs("app.api.routes.auth", level="ERROR") as captured,
        ):
            response = self.client.post(
                "/api/auth/forgot-password",
                json={"email": "student@example.com"},
            )

        log_output = "\n".join(captured.output)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(sent_values["token"], response.text)
        self.assertNotIn(sent_values["token"], log_output)
        self.assertNotIn("NeverLogThisPassword123!", log_output)
        with Session(self.engine) as db:
            token_record = db.scalar(select(PasswordResetToken))
            self.assertIsNotNone(token_record.used_at)

    def test_forgot_password_requests_are_rate_limited(self) -> None:
        for _ in range(5):
            response = self.client.post(
                "/api/auth/forgot-password",
                json={"email": "nobody@example.com"},
            )
            self.assertEqual(response.status_code, 200)

        limited = self.client.post(
            "/api/auth/forgot-password",
            json={"email": "nobody@example.com"},
        )
        self.assertEqual(limited.status_code, 429)

    def test_reset_token_validation_attempts_are_rate_limited(self) -> None:
        payload = {
            "token": generate_secure_token(),
            "new_password": "NewStudentPass123!",
            "confirm_password": "NewStudentPass123!",
        }
        for _ in range(10):
            response = self.client.post("/api/auth/reset-password", json=payload)
            self.assertEqual(response.status_code, 400)

        limited = self.client.post("/api/auth/reset-password", json=payload)
        self.assertEqual(limited.status_code, 429)

    def test_new_recovery_request_invalidates_older_tokens(self) -> None:
        with Session(self.engine) as db:
            user = User(
                full_name="Student",
                email="student@example.com",
                hashed_password="existing-password-hash",
            )
            db.add(user)
            db.flush()
            old_token = PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(generate_secure_token()),
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
            db.add(old_token)
            db.commit()
            user_id = user.id
            old_token_id = old_token.id

        with self.smtp_settings_patch(), patch(
            "app.api.routes.auth.send_password_reset_email"
        ):
            response = self.client.post(
                "/api/auth/forgot-password",
                json={"email": "student@example.com"},
            )

        self.assertEqual(response.status_code, 200)
        with Session(self.engine) as db:
            records = db.scalars(
                select(PasswordResetToken).where(PasswordResetToken.user_id == user_id)
            ).all()
            old_record = db.get(PasswordResetToken, old_token_id)
            current_records = [record for record in records if record.id != old_token_id]
            self.assertIsNotNone(old_record.used_at)
            self.assertEqual(len(current_records), 1)
            self.assertIsNone(current_records[0].used_at)

    def test_expired_and_invalid_reset_tokens_are_rejected(self) -> None:
        with Session(self.engine) as db:
            user = User(
                full_name="Student",
                email="student@example.com",
                hashed_password="existing-password-hash",
            )
            db.add(user)
            db.flush()
            expired_token = generate_secure_token()
            db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=hash_token(expired_token),
                    expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
            db.commit()

        for token in (expired_token, generate_secure_token()):
            response = self.client.post(
                "/api/auth/reset-password",
                json={
                    "token": token,
                    "new_password": "NewStudentPass123!",
                    "confirm_password": "NewStudentPass123!",
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("invalid or has expired", response.json()["detail"])

    def test_reset_token_is_single_use_and_new_password_can_sign_in(self) -> None:
        registration = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "AUST Student",
                "email": "student@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
                "terms_accepted": True,
            },
        )
        self.assertEqual(registration.status_code, 201)
        raw_token = generate_secure_token()
        with Session(self.engine) as db:
            user = db.scalar(select(User).where(User.email == "student@example.com"))
            db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=hash_token(raw_token),
                    expires_at=datetime.now(UTC) + timedelta(minutes=30),
                )
            )
            db.commit()

        reset_payload = {
            "token": raw_token,
            "new_password": "UpdatedStudent456!",
            "confirm_password": "UpdatedStudent456!",
        }
        with self.smtp_unconfigured_patch():
            successful_reset = self.client.post("/api/auth/reset-password", json=reset_payload)
            reused_reset = self.client.post("/api/auth/reset-password", json=reset_payload)
        self.assertEqual(successful_reset.status_code, 200)
        self.assertEqual(reused_reset.status_code, 400)
        self.assertEqual(
            self.client.post(
                "/api/auth/login",
                json={
                    "email": "student@example.com",
                    "password": "UpdatedStudent456!",
                    "remember_me": False,
                },
            ).status_code,
            200,
        )

    def test_reset_email_uses_mocked_tls_smtp_provider(self) -> None:
        from app.services.email_delivery import send_password_reset_email

        with self.smtp_settings_patch(), patch(
            "app.services.email_delivery.smtplib.SMTP"
        ) as smtp_factory:
            smtp = smtp_factory.return_value.__enter__.return_value
            smtp.send_message.return_value = {}
            send_password_reset_email(
                "student@example.com",
                "https://classmate.example/#reset_token=one-time-token",
            )

        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("classmate@example.test", "smtp-secret-for-tests")
        message = smtp.send_message.call_args.args[0]
        body = message.get_body(preferencelist=("plain",)).get_content()
        self.assertIn("one-time-token", body)
        self.assertIn("30 minutes", body)
        self.assertNotIn("smtp-secret-for-tests", message.as_string())

    def test_password_reset_invalidates_all_reset_tokens_and_old_sessions(self) -> None:
        register = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "AUST Student",
                "email": "student@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
                "terms_accepted": True,
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
            with (
                self.smtp_settings_patch(),
                patch("app.api.routes.auth.send_password_changed_email") as send_changed,
            ):
                response = self.client.post(
                    "/api/auth/reset-password",
                    json={
                        "token": used_token,
                        "new_password": "UpdatedStudent456!",
                        "confirm_password": "UpdatedStudent456!",
                    },
                )
            self.assertEqual(response.status_code, 200)
            send_changed.assert_called_once_with("student@example.com")
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
        encryption_key = Fernet.generate_key().decode("ascii")
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
        ):
            start = self.client.get("/api/auth/google/start", follow_redirects=False)
            state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
            response = self.client.get(
                "/api/auth/google/callback",
                params={"error": "access_denied", "state": state},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertIn("google=denied", response.headers["location"])

    def test_google_callback_rejects_missing_session_cookie(self) -> None:
        encryption_key = Fernet.generate_key().decode("ascii")
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
        ):
            start = self.client.get("/api/auth/google/start", follow_redirects=False)
            state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
            self.client.cookies.clear()
            callback = self.client.get(
                "/api/auth/google/callback",
                params={"state": state, "code": "authorization-code"},
                follow_redirects=False,
            )

        self.assertEqual(callback.status_code, 400)
        self.assertEqual(
            callback.json()["detail"],
            "Google sign-in state did not match.",
        )

    def test_google_callback_rejects_expired_state(self) -> None:
        encryption_key = Fernet.generate_key().decode("ascii")
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
        ):
            start = self.client.get("/api/auth/google/start", follow_redirects=False)
            state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

        expired_time = datetime.now(UTC) + timedelta(minutes=11)
        with patch("app.api.routes.auth.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = expired_time
            callback = self.client.get(
                "/api/auth/google/callback",
                params={"state": state, "code": "authorization-code"},
                follow_redirects=False,
            )

        self.assertEqual(callback.status_code, 400)
        self.assertIn("state expired", callback.json()["detail"])

    def test_google_callback_supports_repeated_login_attempts(self) -> None:
        encryption_key = Fernet.generate_key().decode("ascii")
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
        ):
            first = self.client.get("/api/auth/google/start", follow_redirects=False)
            first_state = parse_qs(urlparse(first.headers["location"]).query)["state"][0]
            second = self.client.get("/api/auth/google/start", follow_redirects=False)
            second_state = parse_qs(urlparse(second.headers["location"]).query)["state"][0]

            first_callback = self.client.get(
                "/api/auth/google/callback",
                params={"error": "access_denied", "state": first_state},
                follow_redirects=False,
            )
            second_callback = self.client.get(
                "/api/auth/google/callback",
                params={"error": "access_denied", "state": second_state},
                follow_redirects=False,
            )

        self.assertEqual(first_callback.status_code, 303)
        self.assertEqual(second_callback.status_code, 303)
        self.assertIn("google=denied", first_callback.headers["location"])
        self.assertIn("google=denied", second_callback.headers["location"])

    def test_callback_reports_google_401_invalid_token(self) -> None:
        encryption_key = Fernet.generate_key().decode("ascii")
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
        ):
            start = self.client.get("/api/auth/google/start", follow_redirects=False)

        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        flow = MagicMock()
        flow.credentials = MagicMock()
        flow.credentials.granted_scopes = OAUTH_SCOPES
        google_error = HttpError(
            resp=MagicMock(status=401),
            content=b'{"error":"invalid_token"}',
        )
        with (
            patch("app.api.routes.auth.create_oauth_flow", return_value=flow),
            patch("app.api.routes.auth.get_google_profile", side_effect=google_error),
        ):
            response = self.client.get(
                "/api/auth/google/callback",
                params={"state": state, "code": "authorization-code"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("google=token_rejected", response.headers["location"])

    def test_google_signup_requires_consent_before_creating_a_user(self) -> None:
        encryption_key = Fernet.generate_key().decode("ascii")
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
        ):
            start = self.client.get("/api/auth/google/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        flow = MagicMock()
        flow.credentials.granted_scopes = OAUTH_SCOPES
        profile = {
            "id": "new-google-student",
            "email": "new-google-student@example.com",
            "verified_email": True,
            "name": "New Google Student",
        }
        with (
            patch("app.api.routes.auth.create_oauth_flow", return_value=flow),
            patch("app.api.routes.auth.get_google_profile", return_value=profile),
            patch("app.api.routes.auth.save_google_login") as save_login,
        ):
            response = self.client.get(
                "/api/auth/google/callback",
                params={"state": state, "code": "authorization-code"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("google=terms_required", response.headers["location"])
        save_login.assert_not_called()
        with Session(self.engine) as db:
            self.assertIsNone(
                db.scalar(select(User).where(User.email == profile["email"]))
            )

    def test_consented_google_signup_records_server_selected_legal_versions(self) -> None:
        from app.api.routes.auth import PRIVACY_POLICY_VERSION, TERMS_VERSION

        encryption_key = Fernet.generate_key().decode("ascii")
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
        ):
            start = self.client.get(
                "/api/auth/google/start?terms_accepted=true",
                follow_redirects=False,
            )
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        flow = MagicMock()
        flow.credentials.granted_scopes = OAUTH_SCOPES
        flow.credentials.token = "test-access-token"
        flow.credentials.refresh_token = None
        flow.credentials.expiry = None
        profile = {
            "id": "consented-google-student",
            "email": "consented-google-student@example.com",
            "verified_email": True,
            "name": "Consented Google Student",
        }
        with (
            patch("app.api.routes.auth.create_oauth_flow", return_value=flow),
            patch("app.api.routes.auth.get_google_profile", return_value=profile),
            patch("app.api.routes.auth._establish_session"),
        ):
            response = self.client.get(
                "/api/auth/google/callback",
                params={"state": state, "code": "authorization-code"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as db:
            user = db.scalar(select(User).where(User.email == profile["email"]))
            self.assertIsNotNone(user)
            self.assertEqual(user.terms_version, TERMS_VERSION)
            self.assertEqual(user.privacy_policy_version, PRIVACY_POLICY_VERSION)
            self.assertIsNotNone(user.terms_accepted_at)
            self.assertIsNotNone(user.privacy_acknowledged_at)

    def test_callback_rejects_missing_identity_scope_without_fetching_profile(self) -> None:
        encryption_key = Fernet.generate_key().decode("ascii")
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
        ):
            start = self.client.get("/api/auth/google/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        flow = MagicMock()
        flow.credentials.granted_scopes = ["openid", "profile"]
        with (
            patch("app.api.routes.auth.create_oauth_flow", return_value=flow),
            patch("app.api.routes.auth.get_google_profile") as get_profile,
        ):
            response = self.client.get(
                "/api/auth/google/callback",
                params={"state": state, "code": "authorization-code"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("google=scopes_required", response.headers["location"])
        get_profile.assert_not_called()
        with Session(self.engine) as db:
            self.assertEqual(db.query(GoogleAccount).count(), 0)

    def test_expired_user_oauth_callback_does_not_trigger_classroom_sync(self) -> None:
        with Session(self.engine) as db:
            user = User(
                full_name="Expired Student",
                email="expired@example.com",
                hashed_password="not-used",
            )
            plan = Plan(
                code="semester",
                name="Semester",
                amount_paisa=50000,
                currency="PKR",
                duration_months=6,
                is_enabled=True,
            )
            db.add_all(
                [
                    user,
                    plan,
                    LicensingPolicy(
                        id=1,
                        launch_at=datetime.now(UTC) - timedelta(days=31),
                        grandfathering_days=30,
                    ),
                ]
            )
            db.flush()
            db.add(
                License(
                    user_id=user.id,
                    plan_id=plan.id,
                    starts_at=datetime.now(UTC) - timedelta(days=400),
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
            db.commit()
            db.refresh(user)

        encryption_key = Fernet.generate_key().decode("ascii")
        with (
            patch.object(settings, "google_client_id", "client-id"),
            patch.object(settings, "google_client_secret", "client-secret"),
            patch.object(settings, "google_token_encryption_key", encryption_key),
        ):
            start = self.client.get("/api/auth/google/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        flow = MagicMock()
        flow.credentials = MagicMock()
        flow.credentials.granted_scopes = OAUTH_SCOPES
        account = GoogleAccount(
            user_id=user.id,
            google_sub="expired-google-sub",
            google_email=user.email,
            authorized_scopes=OAUTH_SCOPES,
        )
        with (
            patch("app.api.routes.auth.create_oauth_flow", return_value=flow),
            patch("app.api.routes.auth.get_google_profile", return_value={"email": "expired@example.com"}),
            patch("app.api.routes.auth.save_google_login", return_value=user),
            patch("app.api.routes.auth.get_user_google_account", return_value=account),
            patch("app.api.routes.auth.sync_classroom_data") as sync,
        ):
            response = self.client.get(
                "/api/auth/google/callback",
                params={"state": state, "code": "authorization-code"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("google=connected", response.headers["location"])
        sync.assert_not_called()

    def test_me_endpoint_unauthenticated(self) -> None:
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["authenticated"])
        self.assertFalse(data["google_connected"])

    def test_existing_google_account_exposes_missing_scopes_for_reconnect(self) -> None:
        registration = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "Scope Student",
                "email": "scope-student@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
                "terms_accepted": True,
            },
        )
        self.assertEqual(registration.status_code, 201)
        with Session(self.engine) as db:
            db.add(
                GoogleAccount(
                    user_id=registration.json()["user"]["id"],
                    google_sub="scope-google-sub",
                    google_email="scope-student@example.com",
                    authorized_scopes=[],
                )
            )
            db.commit()

        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["google_connected"])
        self.assertTrue(result["google_reconnect_required"])
        self.assertIn(
            "https://www.googleapis.com/auth/classroom.coursework.me",
            result["google_missing_scopes"],
        )
        self.assertNotIn("access_token", result)
        self.assertNotIn("refresh_token", result)

    def test_registration_login_and_logout_session_flow(self) -> None:
        registration = self.client.post(
            "/api/auth/register",
            json={
                "full_name": "AUST Student",
                "email": "student@example.com",
                "password": "SecureStudent123!",
                "confirm_password": "SecureStudent123!",
                "terms_accepted": True,
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

    def test_legacy_signed_session_requires_reauthentication_for_device_registration(self) -> None:
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

            self.assertIsNone(current_user)
            self.assertEqual(request.session, {})

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
