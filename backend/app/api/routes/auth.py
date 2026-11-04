import logging
import os

# Allow OAuth provider (Google) to normalize or modify granted scopes
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError
from oauthlib.oauth2.rfc6749.errors import OAuth2Error
from requests.exceptions import RequestException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_oauth_diagnostics, settings
from app.core.security import validate_google_token_encryption_key
from app.database.dependencies import get_db
from app.models.google_account import GoogleAccount
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


def _frontend_redirect(result: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.frontend_url.rstrip('/')}?google={result}",
        status_code=303,
    )


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Sign in with Google to continue.")
    user = db.get(User, user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Your session expired. Sign in again.")
    return user


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
def start_google_oauth(request: Request) -> RedirectResponse:
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

    logger.info(
        "[OAUTH-CB] state_present=%s, expected_state_present=%s, states_match=%s, code_verifier_present=%s, provider_error=%s",
        bool(state), bool(expected_state), state == expected_state if state and expected_state else False, bool(code_verifier), provider_error,
    )

    if provider_error:
        logger.warning("[OAUTH-CB] Provider returned error: %s", provider_error)
        return _frontend_redirect("denied")
    if not state or not expected_state or state != expected_state:
        logger.error("[OAUTH-CB] State mismatch or missing. Session keys: %s", list(request.session.keys()))
        raise HTTPException(status_code=400, detail="Google sign-in state did not match.")

    code = request.query_params.get("code")
    if not code:
        logger.error("[OAUTH-CB] No authorization code in query params")
        return _frontend_redirect("error")

    logger.info("[OAUTH-CB] Authorization code received (len=%d). Starting token exchange...", len(code))

    try:
        flow = create_oauth_flow(state=state, code_verifier=code_verifier)
        logger.info("[OAUTH-CB] OAuth flow created. redirect_uri=%s, has_code_verifier=%s", flow.redirect_uri, bool(flow.code_verifier))

        flow.fetch_token(code=code)
        logger.info(
            "[OAUTH-CB] Token exchange succeeded. has_token=%s, has_refresh=%s",
            bool(flow.credentials.token), bool(flow.credentials.refresh_token),
        )

        profile = get_google_profile(flow.credentials)
        logger.info(
            "[OAUTH-CB] Profile retrieved. keys=%s, has_email=%s, has_id=%s",
            list(profile.keys()), bool(profile.get("email")), bool(profile.get("id") or profile.get("sub")),
        )

        user = save_google_login(db, profile, flow.credentials)
        logger.info("[OAUTH-CB] User saved. user_id=%d, email_domain=%s", user.id, user.email.split("@")[-1] if user.email else "none")

        try:
            sync_classroom_data(db, user.id, flow.credentials)
            logger.info("[OAUTH-CB] Initial classroom sync completed.")
        except Exception as sync_exc:
            logger.warning("[OAUTH-CB] Classroom initial sync failed (non-blocking): %s", sync_exc)
    except GoogleIntegrationNotConfigured as exc:
        logger.error("[OAUTH-CB] OAuth not configured: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (GoogleAuthError, HttpError, OAuth2Error, RequestException, ValueError) as exc:
        logger.exception("[OAUTH-CB] OAuth completion FAILED at stage. type=%s, msg=%s", type(exc).__name__, exc)
        return _frontend_redirect("error")
    except RuntimeError as exc:
        logger.exception("[OAUTH-CB] Runtime error: type=%s, msg=%s", type(exc).__name__, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[OAUTH-CB] UNEXPECTED error: type=%s, msg=%s", type(exc).__name__, exc)
        return _frontend_redirect("error")

    request.session.clear()
    request.session["user_id"] = user.id
    logger.info("[OAUTH-CB] SUCCESS — user_id=%d stored in session, redirecting to frontend", user.id)
    return _frontend_redirect("connected")


@router.get("/me")
def get_session_user(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if isinstance(user_id, int) else None

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
        }

    account = db.scalar(
        select(GoogleAccount).where(GoogleAccount.user_id == user.id)
    )
    return {
        "authenticated": True,
        "google_connected": account is not None,
        "google_oauth_configured": is_configured,
        "user": {
            "full_name": user.full_name,
            "email": user.email,
            "roll_number": user.roll_number,
            "department": user.department,
            "semester": user.semester,
        },
        "google_email": account.google_email if account else None,
        "last_synced_at": account.last_synced_at.isoformat() if account and account.last_synced_at else None,
    }


@router.post("/google/disconnect")
def disconnect_google(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    account = get_user_google_account(db, user.id)
    if account is not None:
        disconnect_google_account(db, account)
    request.session.clear()
    return {"status": "disconnected"}


@router.post("/logout")
def logout(request: Request) -> dict[str, str]:
    request.session.clear()
    return {"status": "signed_out"}
