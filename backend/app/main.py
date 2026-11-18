import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlunsplit

# Allow OAuth provider (Google) to normalize or modify granted scopes
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.assignments import router as assignments_router
from app.api.routes.classroom import router as classroom_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.health import router as health_router
from app.api.routes.licensing import router as licensing_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.search import router as search_router
from app.core.config import settings
from app.services.classroom_scheduler import create_classroom_scheduler

# Configure root logger so OAuth callback stage logs appear in console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler: BackgroundScheduler | None = None
    if not os.getenv("PYTEST_CURRENT_TEST"):
        scheduler = create_classroom_scheduler()
        scheduler.start()
        app.state.classroom_scheduler = scheduler
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(
    title="ClassMate AI API",
    description="Assignment intelligence and classroom workflow backend for ClassMate AI.",
    version="0.1.0",
    lifespan=lifespan,
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
    https_only=(
        settings.environment.lower() == "production"
        or settings.session_cookie_secure is True
    ),
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


@app.middleware("http")
async def limit_receipt_upload_body(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    if request.method == "POST" and request.url.path in {
        "/api/payments/submit",
        "/api/licenses/renew",
    }:
        raw_length = request.headers.get("content-length")
        if raw_length is None:
            return JSONResponse(
                status_code=411,
                content={"detail": "A Content-Length header is required for receipt uploads."},
            )
        try:
            request_length = int(raw_length)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
        if request_length > settings.payment_receipt_max_bytes + 256 * 1024:
            return JSONResponse(
                status_code=413,
                content={"detail": "Receipt upload exceeds the 5 MiB limit."},
            )
    return await call_next(request)


app.include_router(health_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(assignments_router, prefix="/api")
app.include_router(classroom_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(licensing_router, prefix="/api")
app.include_router(search_router, prefix="/api")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "ClassMate AI backend is running."}
