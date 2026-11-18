from datetime import datetime, timezone
import os
from typing import Any

# Allow OAuth provider (Google) to normalize or modify granted scopes
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import requests
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_google_token, encrypt_google_token
from app.models.course import Course
from app.models.google_account import GoogleAccount
from app.models.user import User

IDENTITY_SCOPES = [
    "openid",
    "email",
    "profile",
]
CLASSROOM_READ_SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
]
CLASSROOM_STUDENT_READ_SCOPES = list(CLASSROOM_READ_SCOPES)
CLASSROOM_SCOPES = [*IDENTITY_SCOPES, *CLASSROOM_READ_SCOPES]
CLASSROOM_WRITE_SCOPES = [
    "https://www.googleapis.com/auth/classroom.coursework.me",
]
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
OAUTH_SCOPES = [
    *IDENTITY_SCOPES,
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    *CLASSROOM_WRITE_SCOPES,
    DRIVE_FILE_SCOPE,
]
GOOGLE_SCOPE_ALIASES = {
    "email": {"https://www.googleapis.com/auth/userinfo.email"},
    "profile": {"https://www.googleapis.com/auth/userinfo.profile"},
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly": {
        "https://www.googleapis.com/auth/classroom.coursework.me",
    },
}


class GoogleIntegrationNotConfigured(RuntimeError):
    pass


class GoogleAccountLinkRequired(ValueError):
    pass


class GoogleScopesMissingError(ValueError):
    def __init__(self, missing_scopes: list[str]):
        self.missing_scopes = missing_scopes
        super().__init__("Google has not granted all required permissions.")


def _normalize_scope_values(scopes: Any) -> set[str] | None:
    if isinstance(scopes, str):
        return set(scopes.split())
    if isinstance(scopes, (list, tuple, set)):
        return {scope for scope in scopes if isinstance(scope, str)}
    return None


def reported_google_scopes(credentials: Credentials) -> set[str] | None:
    """Return only scopes reported in the OAuth token response, if present."""
    return _normalize_scope_values(credentials.granted_scopes)


def granted_google_scopes(credentials: Credentials) -> set[str]:
    """Return reported scopes, falling back only when Google omits the scope field."""
    reported_scopes = reported_google_scopes(credentials)
    if reported_scopes is not None:
        return reported_scopes
    return _normalize_scope_values(credentials.scopes) or set()


def missing_google_scopes(
    granted_scopes: list[str] | set[str] | None,
    required_scopes: list[str] | set[str],
) -> list[str]:
    granted = set(granted_scopes or [])
    missing = []
    for required in set(required_scopes):
        accepted = {required, *GOOGLE_SCOPE_ALIASES.get(required, set())}
        if not accepted.intersection(granted):
            missing.append(required)
    return sorted(missing)


def require_google_scopes(
    granted_scopes: list[str] | set[str] | None,
    required_scopes: list[str] | set[str],
) -> None:
    missing = missing_google_scopes(granted_scopes, required_scopes)
    if missing:
        raise GoogleScopesMissingError(missing)


def _client_config() -> dict[str, Any]:
    if not settings.google_client_id or not settings.google_client_secret:
        raise GoogleIntegrationNotConfigured(
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [
                uri
                for uri in (
                    settings.google_redirect_uri,
                    settings.google_redirect_uri_lan,
                )
                if uri
            ],
        }
    }


def create_oauth_flow(
    state: str | None = None,
    code_verifier: str | None = None,
    redirect_uri: str | None = None,
) -> Flow:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=OAUTH_SCOPES,
        state=state,
        code_verifier=code_verifier,
    )
    flow.redirect_uri = redirect_uri or settings.google_redirect_uri
    return flow


def get_google_profile(credentials: Credentials) -> dict[str, Any]:
    profile = build("oauth2", "v2", credentials=credentials, cache_discovery=False)
    return profile.userinfo().get().execute()


def save_google_login(
    db: Session,
    user: User | None,
    profile: dict[str, Any],
    credentials: Credentials,
    legal_acceptance: tuple[str, str, datetime] | None = None,
) -> User:
    email = profile.get("email")
    email = email.strip().lower() if isinstance(email, str) else None
    google_sub = profile.get("id") or profile.get("sub")
    is_verified = (
        profile.get("verified_email") is True
        or profile.get("email_verified") is True
        or bool(profile.get("verified"))
    )
    if not isinstance(email, str) or not email or not is_verified:
        raise ValueError("Google did not provide a verified email address.")
    if not isinstance(google_sub, str) or not google_sub:
        raise ValueError("Google did not provide a stable account identifier.")
    if not credentials.token:
        raise ValueError("Google did not return an access token.")

    if user is None:
        user = db.scalar(select(User).where(User.google_id == google_sub))
        if user is None:
            existing_google_account = db.scalar(
                select(GoogleAccount).where(GoogleAccount.google_sub == google_sub)
            )
            if existing_google_account is not None:
                user = db.get(User, existing_google_account.user_id)

        if user is None:
            existing_email_user = db.scalar(
                select(User).where(func.lower(User.email) == email)
            )
            if existing_email_user is not None:
                raise GoogleAccountLinkRequired(
                    "An account already exists for this email. Sign in to that account "
                    "before connecting Google."
                )

            full_name = (profile.get("name") or email.split("@")[0]).strip()
            user = User(
                full_name=full_name,
                email=email,
                google_id=google_sub,
                auth_provider="google",
                avatar_url=profile.get("picture"),
                is_verified=True,
                terms_version=legal_acceptance[0] if legal_acceptance else None,
                terms_accepted_at=legal_acceptance[2] if legal_acceptance else None,
                privacy_policy_version=legal_acceptance[1] if legal_acceptance else None,
                privacy_acknowledged_at=legal_acceptance[2] if legal_acceptance else None,
            )
            db.add(user)
            db.flush()
        else:
            if not user.google_id:
                user.google_id = google_sub
            if user.auth_provider == "email":
                user.auth_provider = "both"
            elif not user.auth_provider:
                user.auth_provider = "google"
            if profile.get("picture") and not user.avatar_url:
                user.avatar_url = profile.get("picture")
            user.is_verified = True
    else:
        # Existing authenticated session linking account
        if user.email.strip().lower() != email:
            raise ValueError("The Google account must match the registered Classroom Email.")
        user.google_id = google_sub
        if user.auth_provider == "email":
            user.auth_provider = "both"
        elif not user.auth_provider:
            user.auth_provider = "google"
        if profile.get("picture") and not user.avatar_url:
            user.avatar_url = profile.get("picture")
        user.is_verified = True

    account = db.scalar(select(GoogleAccount).where(GoogleAccount.google_sub == google_sub))
    if account is not None and account.user_id != user.id:
        raise ValueError("The Google account is already linked to another user.")

    linked_account = db.scalar(
        select(GoogleAccount).where(GoogleAccount.user_id == user.id)
    )
    if linked_account is not None and linked_account.google_sub != google_sub:
        raise ValueError("This user is already linked to a different Google account.")

    is_new_google_account = account is None
    if account is None:
        account = GoogleAccount(
            user_id=user.id,
            google_sub=google_sub,
            google_email=email,
        )
        db.add(account)

    reported_scopes = reported_google_scopes(credentials)
    account.google_email = email
    account.encrypted_access_token = encrypt_google_token(credentials.token or "")
    account.encrypted_refresh_token = (
        encrypt_google_token(credentials.refresh_token)
        if credentials.refresh_token
        else account.encrypted_refresh_token
    )
    account.token_expiry = credentials.expiry
    if reported_scopes is not None or is_new_google_account:
        account.authorized_scopes = sorted(granted_google_scopes(credentials))
    db.commit()
    db.refresh(user)
    return user


def get_user_google_account(db: Session, user_id: int) -> GoogleAccount | None:
    return db.scalar(
        select(GoogleAccount)
        .where(GoogleAccount.user_id == user_id)
        .order_by(GoogleAccount.connected_at.desc())
    )


def get_classroom_credentials(db: Session, account: GoogleAccount) -> Credentials:
    require_google_scopes(account.authorized_scopes, CLASSROOM_STUDENT_READ_SCOPES)
    if not settings.google_client_id or not settings.google_client_secret:
        raise GoogleIntegrationNotConfigured(
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )
    if not account.encrypted_access_token:
        raise RefreshError("Google account has no stored access token.")

    refresh_token = (
        decrypt_google_token(account.encrypted_refresh_token)
        if account.encrypted_refresh_token
        else None
    )
    expiry = account.token_expiry
    if expiry is not None and expiry.tzinfo is not None:
        expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)

    credentials = Credentials(
        token=decrypt_google_token(account.encrypted_access_token),
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=account.authorized_scopes or CLASSROOM_SCOPES,
        expiry=expiry,
    )
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    should_refresh = False
    if credentials.expired or not credentials.valid:
        should_refresh = True
    elif credentials.expiry:
        exp = credentials.expiry.replace(tzinfo=None) if credentials.expiry.tzinfo else credentials.expiry
        if (exp - now_utc).total_seconds() < 120:
            should_refresh = True

    if should_refresh:
        if not credentials.refresh_token:
            raise RefreshError("Google refresh token is unavailable.")
        credentials.refresh(Request())
        account.encrypted_access_token = encrypt_google_token(credentials.token or "")
        if credentials.refresh_token:
            account.encrypted_refresh_token = encrypt_google_token(credentials.refresh_token)
        account.token_expiry = credentials.expiry
        if credentials.granted_scopes is not None:
            account.authorized_scopes = sorted(granted_google_scopes(credentials))
        db.commit()
    return credentials


def revoke_google_token(token: str | None) -> None:
    if not token:
        return
    try:
        requests.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": token},
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=5,
        )
    except Exception:
        pass


def delete_google_account(db: Session, account: GoogleAccount) -> None:
    db.delete(account)
    db.commit()


def disconnect_google_account(db: Session, account: GoogleAccount) -> None:
    token_to_revoke = None
    try:
        if account.encrypted_refresh_token:
            token_to_revoke = decrypt_google_token(account.encrypted_refresh_token)
        elif account.encrypted_access_token:
            token_to_revoke = decrypt_google_token(account.encrypted_access_token)
    except Exception:
        pass

    if token_to_revoke:
        revoke_google_token(token_to_revoke)

    db.execute(
        update(Course).where(Course.user_id == account.user_id).values(is_active=False)
    )
    delete_google_account(db, account)


def google_http_status(error: HttpError) -> int | None:
    return getattr(error.resp, "status", None)


def is_google_insufficient_permissions(error: HttpError) -> bool:
    if google_http_status(error) != 403:
        return False
    content = error.content.decode("utf-8", errors="replace") if error.content else ""
    detail = f"{error} {content}".casefold()
    return "insufficientpermissions" in detail or "insufficient permission" in detail
