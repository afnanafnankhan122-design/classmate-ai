import logging
import os

# Allow OAuth provider (Google) to normalize or modify granted scopes
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.classroom import router as classroom_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.health import router as health_router
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
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(classroom_router, prefix="/api")
app.include_router(search_router, prefix="/api")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "ClassMate AI backend is running."}
