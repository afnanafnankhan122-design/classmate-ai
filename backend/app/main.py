import logging
import os
from urllib.parse import urlsplit, urlunsplit

# Allow OAuth provider (Google) to normalize or modify granted scopes
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.classroom import router as classroom_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.health import router as health_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.search import router as search_router
from app.core.config import settings

# Configure root logger so OAuth callback stage logs appear in console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


app = FastAPI(
    title="ClassMate AI API",
    description="Assignment intelligence and classroom workflow backend for ClassMate AI.",
    version="0.1.0",
)


def _allowed_cors_origins() -> list[str]:
    origins = set(settings.backend_cors_origins)
    origins.add(settings.frontend_url)

    if settings.environment.lower() != "production":
        for origin in tuple(origins):
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
                continue
            alternate_host = "127.0.0.1" if parsed.hostname == "localhost" else "localhost"
            authority = alternate_host
            if parsed.port is not None:
                authority = f"{authority}:{parsed.port}"
            origins.add(
                urlunsplit((parsed.scheme, authority, parsed.path, parsed.query, parsed.fragment))
            )

    return sorted(origin.rstrip("/") for origin in origins)


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="classmate_session",
    same_site="lax",
    https_only=settings.environment.lower() == "production",
    max_age=60 * 60 * 24 * 14,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def validate_api_request_origin(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    """Reject browser state-changing requests from untrusted origins."""
    if request.url.path.startswith("/api/") and request.method in {
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    }:
        origin = request.headers.get("origin")
        if origin is not None:
            allowed_origins = set(_allowed_cors_origins())
            if origin.rstrip("/") not in allowed_origins:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Request origin is not allowed."},
                )
    return await call_next(request)

app.include_router(health_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(classroom_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(search_router, prefix="/api")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "ClassMate AI backend is running."}
