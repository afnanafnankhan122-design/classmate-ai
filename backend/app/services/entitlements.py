from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.licensing import License, LicensingPolicy
from app.models.user import User


@dataclass(frozen=True)
class LicenseStatus:
    status: str
    active: bool
    source: str | None
    starts_at: datetime | None
    expires_at: datetime | None
    reason: str | None = None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def get_license_status(
    db: Session,
    user: User,
    now: datetime | None = None,
) -> LicenseStatus:
    current_time = _as_utc(now or datetime.now(UTC))
    policy = db.get(LicensingPolicy, 1)
    license_record = db.scalar(select(License).where(License.user_id == user.id))
    if license_record is not None and license_record.revoked_at is not None:
        return LicenseStatus(
            "revoked",
            False,
            "paid",
            _as_utc(license_record.starts_at),
            _as_utc(license_record.expires_at),
            "This license has been revoked.",
        )
    if policy is None or policy.launch_at is None:
        return LicenseStatus("active", True, "prelaunch", None, None)
    launch_at = _as_utc(policy.launch_at)
    if current_time < launch_at:
        return LicenseStatus("active", True, "prelaunch", launch_at, None)

    if license_record is not None:
        starts_at = _as_utc(license_record.starts_at)
        expires_at = _as_utc(license_record.expires_at)
        if starts_at <= current_time < expires_at:
            return LicenseStatus("active", True, "paid", starts_at, expires_at)
        return LicenseStatus("expired", False, "paid", starts_at, expires_at)

    user_created_at = _as_utc(user.created_at)
    grandfather_expires_at = launch_at + timedelta(days=policy.grandfathering_days)
    if user_created_at <= launch_at and current_time < grandfather_expires_at:
        return LicenseStatus(
            "active",
            True,
            "grandfathered",
            launch_at,
            grandfather_expires_at,
        )
    if user_created_at <= launch_at and current_time >= grandfather_expires_at:
        return LicenseStatus(
            "expired",
            False,
            "grandfathered",
            launch_at,
            grandfather_expires_at,
        )

    return LicenseStatus("unlicensed", False, None, None, None)


def require_active_license(db: Session, user: User) -> LicenseStatus:
    status = get_license_status(db, user)
    if not status.active:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail="An active semester license is required for this action.",
        )
    return status
