from contextlib import contextmanager
from datetime import datetime, UTC, timedelta
import hashlib
import re
from threading import Lock
from typing import Iterator

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.device_session import DeviceSession
from app.models.user import User

DEVICE_COOKIE_NAME = "classmate_device"
MAX_ACTIVE_DEVICES = 2
DEVICE_COOKIE_SECONDS = 60 * 60 * 24 * 365
_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,128}$")
_user_locks: dict[int, Lock] = {}
_user_locks_guard = Lock()


class DeviceLimitReached(RuntimeError):
    pass


def _lock_for_user(user_id: int) -> Lock:
    with _user_locks_guard:
        return _user_locks.setdefault(user_id, Lock())


@contextmanager
def device_registration_lock(user_id: int) -> Iterator[None]:
    lock = _lock_for_user(user_id)
    with lock:
        yield


def _device_hash(device_id: str) -> str:
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()


def _device_name(user_agent: str | None) -> str:
    agent = (user_agent or "").casefold()
    if "edg/" in agent:
        browser = "Edge"
    elif "opr/" in agent or "opera" in agent:
        browser = "Opera"
    elif "firefox/" in agent:
        browser = "Firefox"
    elif "chrome/" in agent and "chromium" not in agent:
        browser = "Chrome"
    elif "safari/" in agent and "chrome/" not in agent:
        browser = "Safari"
    else:
        browser = "Unknown browser"

    if "ipad" in agent or "tablet" in agent:
        device_type = "Tablet"
    elif any(marker in agent for marker in ("mobile", "iphone", "android")):
        device_type = "Mobile"
    elif agent:
        device_type = "Desktop"
    else:
        device_type = "Device"
    return f"{device_type} · {browser}"


def device_id_from_request(request: Request) -> str | None:
    device_id = request.cookies.get(DEVICE_COOKIE_NAME)
    if device_id is None or not _DEVICE_ID_PATTERN.fullmatch(device_id):
        return None
    return device_id


def register_device_session(
    db: Session,
    request: Request,
    user: User,
    remember_me: bool,
) -> tuple[DeviceSession, str, bool]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(
        seconds=60 * 60 * 24 * 14 if remember_me else 60 * 60 * 8
    )
    device_id = device_id_from_request(request)
    new_device_cookie = device_id is None
    if device_id is None:
        import secrets

        device_id = secrets.token_urlsafe(32)
    device_hash = _device_hash(device_id)

    with device_registration_lock(user.id):
        # This write serializes registration by user in PostgreSQL and obtains
        # SQLite's write lock before counting devices.
        db.execute(
            update(User)
            .where(User.id == user.id)
            .values(auth_version=User.auth_version)
        )
        existing = db.scalar(
            select(DeviceSession).where(
                DeviceSession.user_id == user.id,
                DeviceSession.device_hash == device_hash,
            )
        )
        active = db.scalars(
            select(DeviceSession).where(
                DeviceSession.user_id == user.id,
                DeviceSession.revoked_at.is_(None),
                DeviceSession.expires_at > now,
            )
        ).all()
        existing_is_active = existing is not None and is_active_device_session(existing, now)
        other_active = [record for record in active if existing is None or record.id != existing.id]
        if (
            not user.is_admin
            and not existing_is_active
            and len(other_active) >= MAX_ACTIVE_DEVICES
        ):
            db.rollback()
            raise DeviceLimitReached

        if existing is None:
            existing = DeviceSession(
                user_id=user.id,
                device_hash=device_hash,
                device_name=_device_name(request.headers.get("user-agent")),
                created_at=now,
            )
            db.add(existing)
        else:
            existing.device_name = _device_name(request.headers.get("user-agent"))
        existing.last_activity = now
        existing.expires_at = expires_at
        existing.revoked_at = None
        db.flush()
        db.commit()
        db.refresh(existing)
    return existing, device_id, new_device_cookie


def get_device_session(
    db: Session,
    user_id: int,
    device_session_id: int,
) -> DeviceSession | None:
    return db.scalar(
        select(DeviceSession).where(
            DeviceSession.id == device_session_id,
            DeviceSession.user_id == user_id,
        )
    )


def is_active_device_session(record: DeviceSession, now: datetime | None = None) -> bool:
    current_time = now or datetime.now(UTC)
    expiration = record.expires_at
    if expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=UTC)
    return record.revoked_at is None and expiration > current_time
