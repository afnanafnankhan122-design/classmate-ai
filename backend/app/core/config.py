from functools import lru_cache
import json
import logging
import os
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)

# Determine backend directory and exact .env file location
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BACKEND_DIR / ".env"

# Allow OAuth provider (Google) to normalize or modify granted scopes without raising Warning
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

# Clear out any empty environment variables that could inadvertently override .env values
for _var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_TOKEN_ENCRYPTION_KEY"):
    if _var in os.environ and not os.environ[_var].strip():
        del os.environ[_var]

# Load backend/.env file via python-dotenv if present
if ENV_FILE.is_file():
    load_dotenv(dotenv_path=ENV_FILE)
else:
    load_dotenv()


class Settings(BaseSettings):
    app_name: str = "ClassMate AI"
    environment: str = "development"
    database_url: str = "sqlite:///./classmate_ai.db"
    secret_key: str = "change-me-in-production"
    backend_cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"
    google_token_encryption_key: str = ""
    frontend_url: str = "http://localhost:3000"
    app_timezone: str = "Asia/Karachi"
    groq_api_key: str = ""

    @field_validator("database_url", mode="before")
    @classmethod
    def resolve_database_url(cls, value: str) -> str:
        if isinstance(value, str) and value.startswith("sqlite:///"):
            raw_path = value.removeprefix("sqlite:///")
            if not os.path.isabs(raw_path):
                if raw_path.startswith("./") or raw_path.startswith(".\\"):
                    raw_path = raw_path[2:]
                abs_db = (BACKEND_DIR / raw_path).resolve()
                return f"sqlite:///{abs_db.as_posix()}"
        return value

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            if value.lstrip().startswith("["):
                parsed_value = json.loads(value)
                if isinstance(parsed_value, list) and all(
                    isinstance(origin, str) for origin in parsed_value
                ):
                    return parsed_value
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("app_timezone")
    @classmethod
    def validate_app_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"APP_TIMEZONE must be a valid IANA timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def require_production_session_secret(self) -> "Settings":
        if (
            self.environment.lower() == "production"
            and self.secret_key == "change-me-in-production"
        ):
            raise ValueError("Set a unique SECRET_KEY before running in production.")
        return self

    model_config = SettingsConfigDict(
        env_file=(str(ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def get_oauth_diagnostics() -> dict[str, Any]:
    """Return safe diagnostics showing whether OAuth variables are loaded, never their values."""
    s = get_settings()
    return {
        "env_file_path": str(ENV_FILE),
        "env_file_exists": ENV_FILE.is_file(),
        "google_client_id_present": bool(s.google_client_id.strip()),
        "google_client_secret_present": bool(s.google_client_secret.strip()),
        "google_token_encryption_key_present": bool(s.google_token_encryption_key.strip()),
        "google_redirect_uri": s.google_redirect_uri,
    }


_diag = get_oauth_diagnostics()
logger.info(
    "OAuth configuration: env_file_exists=%s, client_id_present=%s, client_secret_present=%s, encryption_key_present=%s",
    _diag["env_file_exists"],
    _diag["google_client_id_present"],
    _diag["google_client_secret_present"],
    _diag["google_token_encryption_key_present"],
)
