"""Authentication security utilities: password hashing, token generation, and rate limiting."""

from collections import defaultdict
from datetime import datetime, UTC, timedelta
import hashlib
import re
import secrets
import bcrypt

# Password strength criteria:
# At least 8 characters
# At least one uppercase letter
# At least one lowercase letter
# At least one number or special character
_MIN_LENGTH = 8


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt with salt."""
    if not password:
        raise ValueError("Password cannot be empty.")
    pwd_bytes = password.encode("utf-8")
    if len(pwd_bytes) > 72:
        raise ValueError("Password must be no more than 72 UTF-8 bytes.")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password strength and return (is_valid, error_message)."""
    if len(password) < _MIN_LENGTH:
        return False, f"Password must be at least {_MIN_LENGTH} characters long."
    if len(password.encode("utf-8")) > 72:
        return False, "Password must be no more than 72 UTF-8 bytes."
    if not re.search(r"[a-z]", password):
        return False, "Password must include at least one lowercase letter."
    if not re.search(r"[A-Z]", password):
        return False, "Password must include at least one uppercase letter."
    if not re.search(r"[0-9]", password) and not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must include at least one digit or special character."
    return True, ""


def generate_secure_token() -> str:
    """Generate a high-entropy URL-safe random token for password resets."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Compute SHA-256 hash of a reset token for safe database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class InMemoryRateLimiter:
    """Simple sliding-window rate limiter to protect sensitive auth endpoints."""

    def __init__(self) -> None:
        # key -> list of timestamp floats
        self._history: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        now = datetime.now(UTC).timestamp()
        cutoff = now - window_seconds
        # Clean older entries
        recent = [t for t in self._history[key] if t > cutoff]
        self._history[key] = recent

        if len(recent) >= max_attempts:
            return False

        self._history[key].append(now)
        return True

    def reset(self, key: str) -> None:
        self._history.pop(key, None)


# Global rate limiter instances for auth endpoints
auth_rate_limiter = InMemoryRateLimiter()
