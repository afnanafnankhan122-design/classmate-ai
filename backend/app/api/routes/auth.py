import logging
import os
from datetime import datetime, UTC

# Allow OAuth provider (Google) to normalize or modify granted scopes
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError
from oauthlib.oauth2.rfc6749.errors import OAuth2Error
from requests.exceptions import RequestException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from app.core.auth_security import (
    auth_rate_limiter,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)
from app.core.config import get_oauth_diagnostics, settings
from app.core.security import validate_google_token_encryption_key
from app.database.dependencies import get_db
from app.models.google_account import GoogleAccount
from app.models.notification import Notification
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.services.google_classroom import sync_classroom_data
from app.services.google_oauth import (
    GoogleIntegrationNotConfigured,
    create_oauth_flow,
    disconnect_google_account,
    get_google_profile,
    get_user_google_account,
    save_google_login,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])
REMEMBERED_SESSION_SECONDS = 60 * 60 * 24 * 14
SESSION_SECONDS = 60 * 60 * 8


def _frontend_redirect(result: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.frontend_url.rstrip('/')}?google={result}",
        status_code=303,
    )


def _session_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    issued_at = request.session.get("authenticated_at")
    auth_version = request.session.get("auth_version")
    remember_me = request.session.get("remember_me") is True
    max_age = REMEMBERED_SESSION_SECONDS if remember_me else SESSION_SECONDS
    now = datetime.now(UTC).timestamp()

    if (
        isinstance(user_id, int)
        and "authenticated_at" not in request.session
        and "auth_version" not in request.session
        and "remember_me" not in request.session
    ):
        legacy_user = db.get(User, user_id)
        if legacy_user is not None:
            _establish_session(request, legacy_user, remember_me=True)
            return legacy_user

    if (
        not isinstance(user_id, int)
        or not isinstance(issued_at, (int, float))
        or not isinstance(auth_version, int)
        or issued_at > now
        or now - issued_at > max_age
    ):
        request.session.clear()
        return None

    user = db.get(User, user_id)
    if user is None or user.auth_version != auth_version:
        request.session.clear()
        return None
    return user


def _establish_session(request: Request, user: User, remember_me: bool) -> None:
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["auth_version"] = user.auth_version
    request.session["authenticated_at"] = datetime.now(UTC).timestamp()
    request.session["remember_me"] = remember_me


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Dependency: retrieve current authenticated user from session or raise 401."""
    user = _session_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in with your ClassMate AI account to continue.",
        )
    return user


# ── Student Registration ──
@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    data: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Register a new student account using their Classroom Email and password."""
    client_ip = request.client.host if request.client else "unknown"
    if not auth_rate_limiter.is_allowed(f"register:{client_ip}", max_attempts=15, window_seconds=600):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please try again in a few minutes.",
        )

    # Validate passwords match
    if data.password != data.confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match.")

    # Validate password strength
    valid_strength, error_msg = validate_password_strength(data.password)
    if not valid_strength:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    email_clean = data.email.strip().lower()
    full_name_clean = data.full_name.strip()

    # Check for duplicate account
    existing_user = db.scalar(
        select(User).where(func.lower(User.email) == email_clean)
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this Classroom Email already exists. Please log in.",
        )

    user = User(
        full_name=full_name_clean,
        email=email_clean,
        hashed_password=hash_password(data.password),
        is_verified=False,
    )
    db.add(user)

    db.flush()

    # Create a welcoming notification
    welcome_notif = Notification(
        user_id=user.id,
        title="Welcome to ClassMate AI!",
        message="Your student account has been created. Connect your Google Classroom to synchronize coursework and deadlines.",
        category="system",
        is_read=False,
    )
    db.add(welcome_notif)
    db.commit()
    db.refresh(user)

    # Establish authenticated session
    _establish_session(request, user, remember_me=True)

    return {
        "status": "registered",
        "message": "Account created successfully.",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "email_verified": user.is_verified,
        },
    }


# ── Student Login ──
@router.post("/login")
def login(
    data: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Authenticate a student using Classroom Email and password."""
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"login:{client_ip}:{data.email.lower()}"
    if not auth_rate_limiter.is_allowed(rate_key, max_attempts=8, window_seconds=300):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please wait 5 minutes before trying again.",
        )

    email_clean = data.email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email_clean))

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Classroom Email or password.",
        )

    # Check if account has a password configured
    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Classroom Email or password.",
        )

    if not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Classroom Email or password.",
        )

    # Reset rate limiting upon successful login
    auth_rate_limiter.reset(rate_key)

    # Establish session
    _establish_session(request, user, remember_me=data.remember_me)

    return {
        "status": "authenticated",
        "message": "Signed in successfully.",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "roll_number": user.roll_number,
            "department": user.department,
            "semester": user.semester,
        },
    }


# ── Current Authenticated Student Session ──
@router.get("/me")
def get_session_user(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Return the currently authenticated student session details, Google status, and notifications count."""
    user = _session_user(request, db)

    try:
        validate_google_token_encryption_key()
        token_encryption_configured = True
    except RuntimeError:
        token_encryption_configured = False

    is_configured = bool(
        settings.google_client_id
        and settings.google_client_secret
        and token_encryption_configured
    )

    if user is None:
        request.session.clear()
        return {
            "authenticated": False,
            "google_connected": False,
            "google_oauth_configured": is_configured,
            "user": None,
        }

    account = db.scalar(
        select(GoogleAccount).where(GoogleAccount.user_id == user.id)
    )

    total_unread = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read.is_(False)).count()

    return {
        "authenticated": True,
        "google_connected": account is not None,
        "google_oauth_configured": is_configured,
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "roll_number": user.roll_number,
            "department": user.department,
            "semester": user.semester,
            "avatar_url": user.avatar_url,
            "email_verified": user.is_verified,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "google_email": account.google_email if account else None,
        "last_synced_at": account.last_synced_at.isoformat() if account and account.last_synced_at else None,
        "unread_notifications": total_unread,
    }


# ── Logout ──
@router.post("/logout")
def logout(request: Request) -> dict[str, str]:
    """Invalidate student session and clear session cookies."""
    request.session.clear()
    return {"status": "signed_out"}


# ── Forgot Password Request ──
@router.post("/forgot-password")
def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
) -> dict:
    """Return a generic response while no email delivery provider is configured."""
    client_ip = request.client.host if request.client else "unknown"
    if not auth_rate_limiter.is_allowed(f"forgot:{client_ip}", max_attempts=5, window_seconds=600):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password recovery attempts. Please try again later.",
        )

    # Email delivery is not configured in this application. Do not create an
    # unusable token or expose one in a response/log; preserve a generic reply.
    return {
        "status": "ok",
        "message": "If an account exists, password reset instructions will be sent when email delivery is configured.",
    }


# ── Reset Password Execution ──
@router.post("/reset-password")
def reset_password(
    data: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Validate token and set a new account password."""
    client_ip = request.client.host if request.client else "unknown"
    if not auth_rate_limiter.is_allowed(f"reset:{client_ip}", max_attempts=10, window_seconds=600):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset attempts. Please try again later.",
        )
    if data.new_password != data.confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match.")

    valid_strength, error_msg = validate_password_strength(data.new_password)
    if not valid_strength:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    token_hash = hash_token(data.token.strip())
    now_utc = datetime.now(UTC)

    token_record = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now_utc,
        )
    )

    if token_record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The password reset link is invalid or has expired. Please request a new one.",
        )

    consumed = db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.id == token_record.id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now_utc,
        )
        .values(used_at=now_utc)
        .execution_options(synchronize_session=False)
    )
    if consumed.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The password reset link is invalid or has expired. Please request a new one.",
        )

    user = token_record.user
    user.hashed_password = hash_password(data.new_password)
    user.auth_version += 1
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now_utc)
        .execution_options(synchronize_session=False)
    )

    notif = Notification(
        user_id=user.id,
        title="Security Alert: Password Changed",
        message="Your ClassMate AI account password was successfully reset.",
        category="security",
        is_read=False,
    )
    db.add(notif)
    db.commit()
    request.session.clear()

    return {
        "status": "password_reset_success",
        "message": "Your password has been reset successfully. Please log in with your new password.",
    }


# ── Update Profile ──
@router.patch("/profile")
def update_profile(
    data: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Update profile details for the authenticated student."""
    if data.full_name is not None and data.full_name.strip():
        user.full_name = data.full_name.strip()
    if data.roll_number is not None:
        user.roll_number = data.roll_number.strip() if data.roll_number else None
    if data.department is not None:
        user.department = data.department.strip() if data.department else None
    if data.semester is not None:
        user.semester = data.semester.strip() if data.semester else None

    user.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)

    return {
        "status": "profile_updated",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "roll_number": user.roll_number,
            "department": user.department,
            "semester": user.semester,
        },
    }


# ── Change Password ──
@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Change account password for the authenticated student."""
    if user.hashed_password:
        if not verify_password(data.current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your current password is incorrect.",
            )

    if data.new_password != data.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password and confirmation do not match.",
        )

    valid_strength, error_msg = validate_password_strength(data.new_password)
    if not valid_strength:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    user.hashed_password = hash_password(data.new_password)
    user.updated_at = datetime.now(UTC)
    user.auth_version += 1

    notif = Notification(
        user_id=user.id,
        title="Security Alert: Password Changed",
        message="Your account password was updated successfully from Account Settings.",
        category="security",
        is_read=False,
    )
    db.add(notif)
    db.commit()
    request.session["auth_version"] = user.auth_version

    return {"status": "password_changed", "message": "Password changed successfully."}


# ── Google OAuth Diagnostics & Flow ──
@router.get("/google/diagnostics")
def get_google_oauth_diagnostics() -> dict:
    try:
        validate_google_token_encryption_key()
        encryption_key_valid = True
    except RuntimeError:
        encryption_key_valid = False

    diag = get_oauth_diagnostics()
    return {
        **diag,
        "google_token_encryption_key_valid": encryption_key_valid,
    }


@router.get("/google/start")
def start_google_oauth(
    request: Request,
    user: User = Depends(get_current_user),
) -> RedirectResponse:
    try:
        validate_google_token_encryption_key()
        flow = create_oauth_flow()
    except (GoogleIntegrationNotConfigured, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    request.session["oauth_state"] = state
    if getattr(flow, "code_verifier", None):
        request.session["code_verifier"] = flow.code_verifier
    return RedirectResponse(authorization_url, status_code=302)


@router.get("/google/callback")
def complete_google_oauth(
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    logger.info("[OAUTH-CB] Callback entered. query_params keys: %s", list(request.query_params.keys()))
    provider_error = request.query_params.get("error")
    state = request.query_params.get("state")
    expected_state = request.session.pop("oauth_state", None)
    code_verifier = request.session.pop("code_verifier", None)

    if provider_error:
        logger.warning("[OAUTH-CB] Provider returned error: %s", provider_error)
        return _frontend_redirect("denied")
    if not state or not expected_state or state != expected_state:
        logger.error("[OAUTH-CB] State mismatch or missing.")
        raise HTTPException(status_code=400, detail="Google sign-in state did not match.")

    code = request.query_params.get("code")
    if not code:
        logger.error("[OAUTH-CB] No authorization code in query params")
        return _frontend_redirect("error")

    try:
        flow = create_oauth_flow(state=state, code_verifier=code_verifier)
        flow.fetch_token(code=code)
        profile = get_google_profile(flow.credentials)
        google_email = (profile.get("email") or "").strip().lower()

        # Security check: If student is already logged in, check that the Google account email matches their registered Classroom Email!
        user = _session_user(request, db)
        if user is None:
            return _frontend_redirect("login_required")
        if not google_email or user.email.strip().lower() != google_email:
            return _frontend_redirect("email_mismatch")

        user = save_google_login(db, user, profile, flow.credentials)
        logger.info("[OAUTH-CB] Google account linked to authenticated user_id=%d", user.id)

        # Sync coursework
        try:
            sync_classroom_data(db, user.id, flow.credentials)
            logger.info("[OAUTH-CB] Initial classroom sync completed.")
            # Record notification
            sync_notif = Notification(
                user_id=user.id,
                title="Classroom Synchronized",
                message="Google Classroom was linked and coursework synchronized successfully.",
                category="sync",
                is_read=False,
            )
            db.add(sync_notif)
            db.commit()
        except Exception as sync_exc:
            logger.warning("[OAUTH-CB] Classroom initial sync failed (non-blocking): %s", sync_exc)

    except GoogleIntegrationNotConfigured as exc:
        logger.error("[OAUTH-CB] OAuth not configured: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (GoogleAuthError, HttpError, OAuth2Error, RequestException, ValueError) as exc:
        logger.exception("[OAUTH-CB] OAuth completion FAILED: %s", exc)
        return _frontend_redirect("error")
    except Exception as exc:
        logger.exception("[OAUTH-CB] Unexpected OAuth error: %s", exc)
        return _frontend_redirect("error")

    # Set session
    _establish_session(
        request,
        user,
        remember_me=request.session.get("remember_me") is True,
    )
    logger.info("[OAUTH-CB] SUCCESS: user_id=%d session established", user.id)
    return _frontend_redirect("connected")


@router.post("/google/disconnect")
def disconnect_google(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Disconnect Google Classroom from the student's ClassMate AI account without logging them out."""
    account = get_user_google_account(db, user.id)
    if account is not None:
        disconnect_google_account(db, account)

    notif = Notification(
        user_id=user.id,
        title="Google Classroom Disconnected",
        message="Your Google Classroom account was unlinked. Reconnect anytime from Account Settings.",
        category="google",
        is_read=False,
    )
    db.add(notif)
    db.commit()

    return {"status": "disconnected"}
