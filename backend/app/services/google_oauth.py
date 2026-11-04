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
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_google_token, encrypt_google_token
from app.models.course import Course
from app.models.google_account import GoogleAccount
from app.models.user import User

CLASSROOM_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.students.readonly",
]


class GoogleIntegrationNotConfigured(RuntimeError):
    pass


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
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def create_oauth_flow(state: str | None = None, code_verifier: str | None = None) -> Flow:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=CLASSROOM_SCOPES,
        state=state,
        code_verifier=code_verifier,
    )
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def get_google_profile(credentials: Credentials) -> dict[str, Any]:
    profile = build("oauth2", "v2", credentials=credentials, cache_discovery=False)
    return profile.userinfo().get().execute()


def save_google_login(
    db: Session,
    profile: dict[str, Any],
    credentials: Credentials,
) -> User:
    email = profile.get("email")
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

    account = db.scalar(select(GoogleAccount).where(GoogleAccount.google_sub == google_sub))
    email_owner = db.scalar(select(User).where(User.email == email))
    if account is not None and email_owner is not None and email_owner.id != account.user_id:
        raise ValueError("This Google email is already associated with a different user.")
    user = db.get(User, account.user_id) if account else email_owner
    if user is None:
        user = User(full_name=profile.get("name") or email, email=email)
        db.add(user)
        db.flush()
    elif user.email != email:
        user.email = email

    if account is not None and account.user_id != user.id:
        raise ValueError("The Google account is already linked to another user.")

    linked_account = db.scalar(
        select(GoogleAccount).where(GoogleAccount.user_id == user.id)
    )
    if linked_account is not None and linked_account.google_sub != google_sub:
        raise ValueError("This user is already linked to a different Google account.")

    if account is None:
        account = GoogleAccount(
            user_id=user.id,
            google_sub=google_sub,
            google_email=email,
        )
        db.add(account)

    account.google_email = email
    account.encrypted_access_token = encrypt_google_token(credentials.token or "")
    account.encrypted_refresh_token = (
        encrypt_google_token(credentials.refresh_token)
        if credentials.refresh_token
        else account.encrypted_refresh_token
    )
    account.token_expiry = credentials.expiry
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
        scopes=CLASSROOM_SCOPES,
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
