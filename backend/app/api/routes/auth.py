import logging
import os
import secrets
import smtplib
from datetime import datetime, UTC, timedelta
from urllib.parse import quote, urlsplit

# Allow OAuth provider (Google) to normalize or modify granted scopes
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
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
    generate_secure_token,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)
from app.core.config import get_oauth_diagnostics, settings
from app.core.security import validate_google_token_encryption_key
from app.database.dependencies import get_db
from app.models.google_account import GoogleAccount
from app.models.device_session import DeviceSession
from app.models.notification import Notification
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.services.google_classroom import sync_classroom_data
from app.services.entitlements import get_license_status
from app.services.email_delivery import (
    PASSWORD_RESET_EXPIRATION_MINUTES,
    send_password_changed_email,
    send_password_reset_email,
)
from app.services.device_sessions import (
    DEVICE_COOKIE_NAME,
    DEVICE_COOKIE_SECONDS,
    MAX_ACTIVE_DEVICES,
    DeviceLimitReached,
    device_id_from_request,
    get_device_session,
    is_active_device_session,
    register_device_session,
)
from app.services.google_oauth import (
    CLASSROOM_READ_SCOPES,
    GoogleAccountLinkRequired,
    GoogleIntegrationNotConfigured,
    IDENTITY_SCOPES,
    OAUTH_SCOPES,
    create_oauth_flow,
    granted_google_scopes,
    missing_google_scopes,
    reported_google_scopes,
    require_google_scopes,
    disconnect_google_account,
    get_google_profile,
    get_user_google_account,
    save_google_login,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])
REMEMBERED_SESSION_SECONDS = 60 * 60 * 24 * 14
SESSION_SECONDS = 60 * 60 * 8
PASSWORD_RESET_TTL = timedelta(minutes=PASSWORD_RESET_EXPIRATION_MINUTES)
TERMS_VERSION = "2026-11-08"
PRIVACY_POLICY_VERSION = "2026-11-08"
OAUTH_STATE_TTL_SECONDS = 10 * 60
MAX_PENDING_OAUTH_FLOWS = 3


def _frontend_redirect(result: str, frontend_url: str | None = None) -> RedirectResponse:
    return RedirectResponse(
        f"{(frontend_url or settings.frontend_url).rstrip('/')}?google={result}",
        status_code=303,
    )


def _configured_google_redirect_uris() -> tuple[str, ...]:
    return tuple(
        uri
        for uri in (settings.google_redirect_uri, settings.google_redirect_uri_lan)
        if uri
    )


def _google_redirect_uri_for_request(request: Request) -> str:
    frontend_origin = _trusted_frontend_origin_for_request(request)
    if frontend_origin is not None:
        frontend_hostname = _normalized_hostname(frontend_origin)
        for callback_uri in _configured_google_redirect_uris():
            if _normalized_hostname(callback_uri) == frontend_hostname:
                return callback_uri

    request_hosts: list[str] = []
    try:
        forwarded_host = request.headers.get("x-forwarded-host")
        if forwarded_host:
            forwarded_hostname = urlsplit(f"//{forwarded_host.split(',', 1)[0].strip()}").hostname
            if forwarded_hostname:
                request_hosts.append(forwarded_hostname.rstrip(".").casefold())
        request_hostname = request.url.hostname
        if request_hostname:
            request_hosts.append(request_hostname.rstrip(".").casefold())
    except ValueError:
        pass

    primary_uri = settings.google_redirect_uri
    lan_uri = settings.google_redirect_uri_lan

    for request_host in request_hosts:
        primary_hostname = _normalized_hostname(primary_uri) if primary_uri else None
        if (
            request_host in {"localhost", "127.0.0.1"}
            and primary_hostname in {"localhost", "127.0.0.1"}
        ):
            return primary_uri
        if primary_hostname == request_host:
            return primary_uri
        if lan_uri and _normalized_hostname(lan_uri) == request_host:
            return lan_uri

    raise HTTPException(
        status_code=400,
        detail="This host is not configured for Google OAuth callbacks.",
    )


def _normalized_hostname(url: str) -> str | None:
    try:
        hostname = urlsplit(url).hostname
    except ValueError:
        return None
    return hostname.rstrip(".").casefold() if hostname else None


def _frontend_url_for_request(request: Request) -> str:
    return _trusted_frontend_origin_for_request(request) or settings.frontend_url.rstrip("/")


def _trusted_frontend_origin_for_request(request: Request) -> str | None:
    allowed_origins = {settings.frontend_url.rstrip("/")}
    allowed_origins.update(origin.rstrip("/") for origin in settings.backend_cors_origins)

    for source in (request.headers.get("origin"), request.headers.get("referer")):
        if not source:
            continue
        try:
            parsed_source = urlsplit(source)
        except ValueError:
            continue
        origin = f"{parsed_source.scheme}://{parsed_source.netloc}"
        if origin in allowed_origins:
            return origin

    for origin in allowed_origins:
        parsed_origin = urlsplit(origin)
        if (
            parsed_origin.scheme == request.url.scheme
            and parsed_origin.hostname == request.url.hostname
        ):
            return origin

    return None


def _session_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    issued_at = request.session.get("authenticated_at")
    auth_version = request.session.get("auth_version")
    remember_me = request.session.get("remember_me") is True
    max_age = REMEMBERED_SESSION_SECONDS if remember_me else SESSION_SECONDS
    now = datetime.now(UTC).timestamp()

    if (
        not isinstance(user_id, int)
        or not isinstance(issued_at, (int, float))
        or not isinstance(auth_version, int)
        or not isinstance(request.session.get("device_session_id"), int)
        or issued_at > now
        or now - issued_at > max_age
    ):
        request.session.clear()
        return None

    user = db.get(User, user_id)
    if user is None or user.auth_version != auth_version:
        request.session.clear()
        return None
    device_id = device_id_from_request(request)
    device_session = get_device_session(
        db,
        user.id,
        request.session["device_session_id"],
    )
    if (
        device_id is None
        or device_session is None
        or device_session.device_hash != hash_token(device_id)
        or not is_active_device_session(device_session)
    ):
        request.session.clear()
        return None
    request.state.device_session = device_session
    activity = device_session.last_activity
    if activity.tzinfo is None:
        activity = activity.replace(tzinfo=UTC)
    if now - activity.timestamp() >= 60:
        device_session.last_activity = datetime.now(UTC)
        db.commit()
    return user


def _establish_session(
    request: Request,
    response: Response,
    db: Session,
    user: User,
    remember_me: bool,
) -> None:
    device_session, device_id, new_device_cookie = register_device_session(
        db,
        request,
        user,
        remember_me,
    )
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["auth_version"] = user.auth_version
    request.session["authenticated_at"] = datetime.now(UTC).timestamp()
    request.session["remember_me"] = remember_me
    request.session["device_session_id"] = device_session.id
    if new_device_cookie:
        response.set_cookie(
            DEVICE_COOKIE_NAME,
            device_id,
            max_age=DEVICE_COOKIE_SECONDS,
            httponly=True,
            secure=(
                settings.environment.lower() == "production"
                or settings.session_cookie_secure is True
            ),
            samesite="lax",
            path="/",
        )


def _password_reset_url_base() -> str:
    try:
        parts = urlsplit(settings.frontend_url)
    except ValueError as exc:
        raise ValueError("FRONTEND_URL must be a trusted absolute HTTP(S) URL.") from exc
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("FRONTEND_URL must be a trusted absolute HTTP(S) URL.")
    if settings.environment.lower() == "production" and parts.scheme != "https":
        raise ValueError("FRONTEND_URL must use HTTPS in production.")
    return settings.frontend_url.rstrip("/")


def _deliver_password_reset_email(
    db: Session,
    token_id: int,
    recipient: str,
    reset_url: str,
) -> None:
    try:
        send_password_reset_email(
            recipient,
            reset_url,
            PASSWORD_RESET_EXPIRATION_MINUTES,
        )
    except (OSError, RuntimeError, smtplib.SMTPException, ValueError) as exc:
        logger.error(
            "Password-reset email delivery failed (error_type=%s)",
            type(exc).__name__,
        )
        db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.id == token_id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        db.commit()


def _deliver_password_changed_email(recipient: str) -> None:
    try:
        send_password_changed_email(recipient)
    except (OSError, RuntimeError, smtplib.SMTPException, ValueError) as exc:
        logger.error(
            "Password-change notification email failed (error_type=%s)",
            type(exc).__name__,
        )


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
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    """Register a new student account using their Classroom Email and password."""
    if not data.terms_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must agree to the Terms of Use and acknowledge the Privacy Policy to register.",
        )

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
            detail="An account with this Classroom Email already exists. Please log in or reset your password.",
        )

    accepted_at = datetime.now(UTC)
    user = User(
        full_name=full_name_clean,
        email=email_clean,
        hashed_password=hash_password(data.password),
        auth_provider="email",
        is_verified=False,
        terms_version=TERMS_VERSION,
        terms_accepted_at=accepted_at,
        privacy_policy_version=PRIVACY_POLICY_VERSION,
        privacy_acknowledged_at=accepted_at,
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
    _establish_session(request, response, db, user, remember_me=True)

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
    response: Response,
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

    # Check if account was created via Google and has no local password yet
    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This account uses Google Sign-In. Continue with Google, then set a password "
                "from Account Settings if you want to add password sign-in."
            ),
        )

    if not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Classroom Email or password.",
        )

    # Reset rate limiting upon successful login
    auth_rate_limiter.reset(rate_key)

    # Establish session
    try:
        _establish_session(request, response, db, user, remember_me=data.remember_me)
    except DeviceLimitReached as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You have reached your maximum of 2 registered devices. Sign in from an "
                "existing device and revoke an old session before registering another device."
            ),
        ) from exc

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
    missing_scopes = missing_google_scopes(
        account.authorized_scopes if account is not None else None,
        OAUTH_SCOPES,
    )
    if account is not None:
        logger.info(
            "[AUTH] Stored Google scopes: granted=%s missing=%s",
            sorted(account.authorized_scopes or []),
            missing_scopes,
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
        "google_missing_scopes": missing_scopes,
        "google_reconnect_required": bool(account and missing_scopes),
        "last_synced_at": account.last_synced_at.isoformat() if account and account.last_synced_at else None,
        "unread_notifications": total_unread,
    }


# ── Logout ──
@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Invalidate student session and clear session cookies."""
    user_id = request.session.get("user_id")
    device_session_id = request.session.get("device_session_id")
    if isinstance(user_id, int) and isinstance(device_session_id, int):
        db.execute(
            update(DeviceSession)
            .where(
                DeviceSession.id == device_session_id,
                DeviceSession.user_id == user_id,
                DeviceSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        db.commit()
    request.session.clear()
    response.delete_cookie("classmate_session", path="/", samesite="lax")
    return {"status": "signed_out"}


@router.get("/devices")
def list_registered_devices(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """List only the authenticated user's registered device sessions."""
    now = datetime.now(UTC)
    current_id = request.session.get("device_session_id")
    devices = db.scalars(
        select(DeviceSession)
        .where(DeviceSession.user_id == user.id)
        .order_by(DeviceSession.created_at.desc(), DeviceSession.id.desc())
    ).all()
    result = []
    active_count = 0
    for device in devices:
        active = is_active_device_session(device, now)
        if active:
            active_count += 1
            device_status = "active"
        elif device.revoked_at is not None:
            device_status = "revoked"
        else:
            device_status = "expired"
        result.append(
            {
                "id": device.id,
                "device_name": device.device_name,
                "registered_at": device.created_at.isoformat(),
                "last_activity": device.last_activity.isoformat(),
                "expires_at": device.expires_at.isoformat(),
                "status": device_status,
                "is_current": device.id == current_id,
            }
        )
    return {
        "devices": result,
        "active_count": active_count,
        "max_devices": MAX_ACTIVE_DEVICES,
        "policy_applies": not user.is_admin,
    }


@router.delete("/devices/{device_session_id}")
def revoke_registered_device(
    device_session_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Revoke one of the authenticated user's own device sessions."""
    now = datetime.now(UTC)
    result = db.execute(
        update(DeviceSession)
        .where(
            DeviceSession.id == device_session_id,
            DeviceSession.user_id == user.id,
            DeviceSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=404, detail="Registered device was not found.")
    db.commit()
    if request.session.get("device_session_id") == device_session_id:
        request.session.clear()
        response.delete_cookie("classmate_session", path="/", samesite="lax")
    return {"status": "device_revoked"}


# ── Forgot Password Request ──
@router.post("/forgot-password")
def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    """Request a reset email without disclosing whether an account exists."""
    client_ip = request.client.host if request.client else "unknown"
    if not auth_rate_limiter.is_allowed(f"forgot:{client_ip}", max_attempts=5, window_seconds=600):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password recovery attempts. Please try again later.",
        )

    reset_link_base: str | None = None
    delivery_configured = settings.smtp_configured
    if delivery_configured:
        try:
            reset_link_base = _password_reset_url_base()
        except ValueError as exc:
            delivery_configured = False
            logger.error(
                "Password-reset email delivery is unavailable (error_type=%s)",
                type(exc).__name__,
            )
    else:
        logger.warning("Password-reset email delivery is not configured.")

    email_clean = str(data.email).strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email_clean))
    if (
        delivery_configured
        and reset_link_base is not None
        and user is not None
        and user.hashed_password
    ):
        now_utc = datetime.now(UTC)
        db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=now_utc)
            .execution_options(synchronize_session=False)
        )
        raw_token = generate_secure_token()
        token_record = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=now_utc + PASSWORD_RESET_TTL,
        )
        db.add(token_record)
        db.commit()
        db.refresh(token_record)
        background_tasks.add_task(
            _deliver_password_reset_email,
            db,
            token_record.id,
            user.email,
            f"{reset_link_base}/#reset_token={quote(raw_token, safe='')}",
        )

    return {
        "status": "ok",
        "message": (
            "If an account exists and supports password sign-in, follow the reset instructions "
            "if they arrive. Google-only accounts should continue with Google Sign-In."
        ),
        "email_delivery_configured": delivery_configured,
    }


# ── Reset Password Execution ──
@router.post("/reset-password")
def reset_password(
    data: ResetPasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
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

    if token_record is None or token_record.user is None or not token_record.user.hashed_password:
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
        update(DeviceSession)
        .where(
            DeviceSession.user_id == user.id,
            DeviceSession.revoked_at.is_(None),
        )
        .values(revoked_at=now_utc)
        .execution_options(synchronize_session=False)
    )
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
    if settings.smtp_configured:
        background_tasks.add_task(_deliver_password_changed_email, user.email)

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
    current_device_session_id = request.session.get("device_session_id")
    other_device_sessions = update(DeviceSession).where(
        DeviceSession.user_id == user.id,
        DeviceSession.revoked_at.is_(None),
    )
    if isinstance(current_device_session_id, int):
        other_device_sessions = other_device_sessions.where(
            DeviceSession.id != current_device_session_id
        )
    db.execute(
        other_device_sessions
        .values(revoked_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )

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
    terms_accepted: bool = False,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        validate_google_token_encryption_key()
        redirect_uri = _google_redirect_uri_for_request(request)
        code_verifier = secrets.token_urlsafe(64)
        flow = create_oauth_flow(
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        flow.oauth2session.scope = list(OAUTH_SCOPES)
    except (GoogleIntegrationNotConfigured, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    existing_oauth_flows = request.session.get("oauth_flows")
    active_user = _session_user(request, db)
    if active_user is None and isinstance(existing_oauth_flows, dict):
        request.session["oauth_flows"] = existing_oauth_flows

    # If the user already has an active session, preserve their user ID for account linking
    if active_user is not None:
        link_user_id = active_user.id
        oauth_device_session_id = request.session.get("device_session_id")
    else:
        link_user_id = None
        oauth_device_session_id = None

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    logger.info("[OAUTH] Google scopes requested: %s", sorted(OAUTH_SCOPES))
    now = datetime.now(UTC).timestamp()
    pending_flows = request.session.get("oauth_flows")
    if not isinstance(pending_flows, dict):
        pending_flows = {}
    pending_flows = {
        key: value
        for key, value in pending_flows.items()
        if isinstance(key, str)
        and isinstance(value, dict)
        and isinstance(value.get("started_at"), (int, float))
        and 0 <= now - value["started_at"] <= OAUTH_STATE_TTL_SECONDS
    }
    pending_flows[state] = {
        "started_at": now,
        "redirect_uri": redirect_uri,
        "frontend_url": _frontend_url_for_request(request),
        "code_verifier": code_verifier,
        "link_user_id": link_user_id,
        "oauth_device_session_id": oauth_device_session_id,
        "terms_accepted": terms_accepted is True and active_user is None,
        "remember_me": request.session.get("remember_me") is True,
    }
    if len(pending_flows) > MAX_PENDING_OAUTH_FLOWS:
        oldest = sorted(
            pending_flows,
            key=lambda key: pending_flows[key]["started_at"],
        )[:-MAX_PENDING_OAUTH_FLOWS]
        for key in oldest:
            pending_flows.pop(key, None)
    request.session["oauth_flows"] = pending_flows
    return RedirectResponse(authorization_url, status_code=302)


@router.get("/google/callback")
def complete_google_oauth(
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    logger.info("[OAUTH-CB] Callback entered. query_params keys: %s", list(request.query_params.keys()))
    provider_error = request.query_params.get("error")
    state = request.query_params.get("state")
    pending_flows = request.session.get("oauth_flows")
    flow_state = pending_flows.pop(state, None) if (
        isinstance(state, str) and isinstance(pending_flows, dict)
    ) else None
    if isinstance(pending_flows, dict):
        if pending_flows:
            request.session["oauth_flows"] = pending_flows
        else:
            request.session.pop("oauth_flows", None)

    if not isinstance(flow_state, dict):
        logger.error("[OAUTH-CB] State mismatch or missing.")
        raise HTTPException(status_code=400, detail="Google sign-in state did not match.")
    started_at = flow_state.get("started_at")
    now = datetime.now(UTC).timestamp()
    if (
        not isinstance(started_at, (int, float))
        or started_at > now
        or now - started_at > OAUTH_STATE_TTL_SECONDS
    ):
        logger.warning("[OAUTH-CB] OAuth state expired or invalid.")
        raise HTTPException(status_code=400, detail="Google sign-in state expired. Please try again.")

    redirect_uri = flow_state.get("redirect_uri")
    frontend_url = flow_state.get("frontend_url")
    code_verifier = flow_state.get("code_verifier")
    link_user_id = flow_state.get("link_user_id")
    oauth_device_session_id = flow_state.get("oauth_device_session_id")
    oauth_terms_accepted = flow_state.get("terms_accepted") is True
    remember_me = flow_state.get("remember_me") is True

    if link_user_id is not None:
        active_user = _session_user(request, db)
        if (
            active_user is None
            or active_user.id != link_user_id
            or request.session.get("device_session_id") != oauth_device_session_id
        ):
            request.session.clear()
            return _frontend_redirect("device_revoked", frontend_url)
    if provider_error:
        logger.warning("[OAUTH-CB] Provider returned error: %s", provider_error)
        return _frontend_redirect("denied", frontend_url)
    if (
        not isinstance(code_verifier, str)
        or not 43 <= len(code_verifier) <= 128
    ):
        raise HTTPException(status_code=400, detail="Google sign-in verifier is missing or invalid.")
    if redirect_uri not in _configured_google_redirect_uris():
        raise HTTPException(status_code=400, detail="Google callback URL is not configured.")

    code = request.query_params.get("code")
    if not code:
        logger.error("[OAUTH-CB] No authorization code in query params")
        return _frontend_redirect("error", frontend_url)

    scopes_need_update = False
    try:
        flow = create_oauth_flow(
            state=state,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        flow.fetch_token(code=code)
        reported_scopes = reported_google_scopes(flow.credentials)
        effective_grants = granted_google_scopes(flow.credentials)
        logger.info("[OAUTH-CB] Google scopes requested: %s", sorted(OAUTH_SCOPES))
        logger.info(
            "[OAUTH-CB] Google scopes returned by token endpoint: %s",
            sorted(reported_scopes) if reported_scopes is not None else "scope field omitted",
        )
        if reported_scopes is None:
            logger.info(
                "[OAUTH-CB] Token response omitted scope; existing stored grants are preserved "
                "rather than expanded from the new request."
            )
        logger.info(
            "[OAUTH-CB] Google effective scope grants: %s",
            sorted(effective_grants),
        )
        try:
            require_google_scopes(
                effective_grants,
                IDENTITY_SCOPES,
            )
        except ValueError:
            logger.warning("[OAUTH-CB] Google did not grant required identity scopes.")
            return _frontend_redirect("scopes_required", frontend_url)

        profile = get_google_profile(flow.credentials)
        google_email = (profile.get("email") or "").strip().lower()

        # Handle Linking vs Direct Sign-In
        if link_user_id is not None:
            user = db.get(User, link_user_id)
            if user is None:
                return _frontend_redirect("error", frontend_url)
            else:
                # Verifying email matches registered Classroom Email
                if not google_email or user.email.strip().lower() != google_email:
                    return _frontend_redirect("email_mismatch", frontend_url)
                user = save_google_login(db, user, profile, flow.credentials)
        else:
            # Public Google Sign-In or Sign-Up from login/register page
            google_sub = profile.get("id") or profile.get("sub")
            existing_google_user = (
                db.scalar(select(User).where(User.google_id == google_sub))
                if isinstance(google_sub, str) and google_sub
                else None
            )
            existing_google_account = (
                db.scalar(select(GoogleAccount).where(GoogleAccount.google_sub == google_sub))
                if isinstance(google_sub, str) and google_sub
                else None
            )
            existing_email_user = (
                db.scalar(select(User).where(func.lower(User.email) == google_email))
                if google_email
                else None
            )
            is_new_google_user = (
                existing_google_user is None
                and existing_google_account is None
                and existing_email_user is None
            )
            if is_new_google_user and not oauth_terms_accepted:
                return _frontend_redirect("terms_required", frontend_url)
            legal_acceptance = None
            if is_new_google_user:
                legal_acceptance = (
                    TERMS_VERSION,
                    PRIVACY_POLICY_VERSION,
                    datetime.now(UTC),
                )
            user = save_google_login(
                db,
                None,
                profile,
                flow.credentials,
                legal_acceptance=legal_acceptance,
            )

        logger.info("[OAUTH-CB] Google account active for user_id=%d", user.id)

        google_account = get_user_google_account(db, user.id)
        missing_read_scopes = missing_google_scopes(
            google_account.authorized_scopes if google_account is not None else None,
            CLASSROOM_READ_SCOPES,
        )
        missing_oauth_scopes = missing_google_scopes(
            google_account.authorized_scopes if google_account is not None else None,
            OAUTH_SCOPES,
        )
        logger.info(
            "[OAUTH-CB] Google scope comparison: requested=%s stored_granted=%s missing=%s",
            sorted(OAUTH_SCOPES),
            sorted(google_account.authorized_scopes or []) if google_account else [],
            missing_oauth_scopes,
        )
        scopes_need_update = bool(missing_oauth_scopes)
        if get_license_status(db, user).active and not missing_read_scopes:
            try:
                sync_classroom_data(db, user.id, flow.credentials)
                logger.info("[OAUTH-CB] Initial classroom sync completed.")
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
                logger.warning(
                    "[OAUTH-CB] Classroom initial sync failed (non-blocking): error_type=%s",
                    type(sync_exc).__name__,
                )
        elif missing_read_scopes:
            logger.warning("[OAUTH-CB] Google account connected with incomplete Classroom read scopes.")
        else:
            logger.info("[OAUTH-CB] Initial classroom sync skipped because the license is inactive.")

    except GoogleIntegrationNotConfigured as exc:
        logger.error("[OAUTH-CB] OAuth not configured: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GoogleAccountLinkRequired:
        logger.info("[OAUTH-CB] Existing email account requires authenticated linking.")
        return _frontend_redirect("account_exists", frontend_url)
    except HttpError as exc:
        if getattr(exc.resp, "status", None) == 401:
            logger.warning(
                "[OAUTH-CB] Google rejected the OAuth access token: status=%s",
                getattr(exc.resp, "status", None),
            )
            return _frontend_redirect("token_rejected", frontend_url)
        logger.warning(
            "[OAUTH-CB] Google API request failed: status=%s",
            getattr(exc.resp, "status", None),
        )
        return _frontend_redirect("error", frontend_url)
    except (GoogleAuthError, OAuth2Error, RequestException, ValueError) as exc:
        logger.warning("[OAUTH-CB] OAuth completion failed: error_type=%s", type(exc).__name__)
        return _frontend_redirect("error", frontend_url)
    except Exception as exc:
        logger.warning("[OAUTH-CB] Unexpected OAuth error: error_type=%s", type(exc).__name__)
        return _frontend_redirect("error", frontend_url)

    # Set session only after Google identity has been confirmed.
    redirect_response = _frontend_redirect(
        "scopes_required" if scopes_need_update else "connected",
        frontend_url,
    )
    try:
        _establish_session(
            request,
            redirect_response,
            db,
            user,
            remember_me=remember_me,
        )
    except DeviceLimitReached:
        request.session.clear()
        return _frontend_redirect("device_limit", frontend_url)
    logger.info("[OAUTH-CB] SUCCESS: user_id=%d session established", user.id)
    return redirect_response


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
