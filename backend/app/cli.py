import argparse
from datetime import UTC, datetime, timedelta
from getpass import getpass
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth_security import hash_password, validate_password_strength, verify_password
from app.core.config import settings
from app.database.session import SessionLocal
from app.models.licensing import LicenseAuditLog, Payment
from app.models.user import User
from app.services.receipt_storage import (
    delete_quarantined_receipt,
    quarantine_receipt,
    restore_quarantined_receipt,
)


_email_adapter = TypeAdapter(EmailStr)


def _read_email(prompt: str) -> str:
    value = input(prompt).strip().lower()
    try:
        return str(_email_adapter.validate_python(value))
    except ValidationError as exc:
        raise ValueError("Enter a valid email address.") from exc


def _read_new_password() -> str:
    password = getpass("New administrator password: ")
    confirmation = getpass("Confirm administrator password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    valid, message = validate_password_strength(password)
    if not valid:
        raise ValueError(message)
    return password


def provision_admin() -> int:
    db = SessionLocal()
    try:
        existing_admins = db.scalars(select(User).where(User.is_admin.is_(True))).all()
        actor: User | None = None
        if existing_admins:
            actor_email = _read_email("Existing administrator email: ")
            actor = db.scalar(select(User).where(User.email == actor_email))
            actor_password = getpass("Existing administrator password: ")
            if (
                actor is None
                or not actor.is_admin
                or not verify_password(actor_password, actor.hashed_password)
            ):
                print("Administrator authorization failed.", file=sys.stderr)
                return 1

        target_email = _read_email("Administrator account email: ")
        target = db.scalar(select(User).where(User.email == target_email))
        if target is None:
            if existing_admins:
                print("The target account must already exist before it can be promoted.", file=sys.stderr)
                return 1
            full_name = input("Administrator full name: ").strip()
            if not full_name or len(full_name) > 255:
                raise ValueError("Enter a name between 1 and 255 characters.")
            password = _read_new_password()
            target = User(
                full_name=full_name,
                email=target_email,
                hashed_password=hash_password(password),
                is_verified=True,
                is_admin=True,
            )
            db.add(target)
            db.flush()
        else:
            if target.is_admin:
                print("This account is already an administrator.", file=sys.stderr)
                return 1
            target_password = getpass("Target account current password: ")
            if not verify_password(target_password, target.hashed_password):
                print("Target account verification failed.", file=sys.stderr)
                return 1
            target.is_admin = True

        db.add(
            LicenseAuditLog(
                user_id=target.id,
                actor_user_id=actor.id if actor else target.id,
                action="admin_provisioned",
                details={"provisioning": "operator_cli"},
            )
        )
        db.commit()
        print(f"Administrator provisioned for {target_email}.")
        return 0
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, ValueError) else "database operation failed"
        print(f"Administrator provisioning failed: {message}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cleanup_receipts(apply: bool, retention_days: int | None = None) -> int:
    days = (
        settings.payment_receipt_retention_days
        if retention_days is None
        else retention_days
    )
    if not 30 <= days <= 3650:
        print("Receipt retention must be between 30 and 3650 days.", file=sys.stderr)
        return 1
    cutoff = datetime.now(UTC) - timedelta(days=days)
    db = SessionLocal()
    try:
        payments = db.scalars(
            select(Payment)
            .where(
                Payment.status.in_(("approved", "rejected")),
                Payment.reviewed_at.is_not(None),
                Payment.reviewed_at < cutoff,
                Payment.receipt_storage_key.is_not(None),
            )
            .order_by(Payment.reviewed_at.asc(), Payment.id.asc())
        ).all()
        if not apply:
            print(f"Dry run: {len(payments)} finalized receipt(s) are eligible for deletion.")
            return 0

        removed = 0
        for payment in payments:
            storage_key = payment.receipt_storage_key
            try:
                quarantine_receipt(storage_key)
            except OSError:
                db.rollback()
                print("Receipt cleanup stopped because a private file could not be deleted.", file=sys.stderr)
                print("Cleanup error: private receipt storage is unavailable.", file=sys.stderr)
                return 1
            payment.receipt_storage_key = None
            payment.receipt_deleted_at = datetime.now(UTC)
            db.add(
                LicenseAuditLog(
                    user_id=payment.user_id,
                    payment_id=payment.id,
                    action="receipt_deleted_by_retention",
                    details={"retention_days": days},
                )
            )
            try:
                db.commit()
            except SQLAlchemyError:
                db.rollback()
                try:
                    restore_quarantined_receipt(storage_key)
                except OSError:
                    print("Receipt metadata failed and a quarantined receipt could not be restored.", file=sys.stderr)
                    return 1
                print("Receipt metadata could not be updated after file deletion.", file=sys.stderr)
                print("Cleanup error: licensing records could not be updated.", file=sys.stderr)
                return 1
            try:
                delete_quarantined_receipt(storage_key)
            except OSError:
                print("Receipt metadata was updated, but a quarantined private file remains.", file=sys.stderr)
                return 1
            removed += 1
        print(f"Deleted {removed} finalized receipt(s); payment and audit records were retained.")
        return 0
    except SQLAlchemyError:
        db.rollback()
        print("Receipt cleanup query failed because the database is unavailable.", file=sys.stderr)
        return 1
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="ClassMate AI operator-only licensing tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("provision-admin", help="Provision or promote an administrator interactively.")
    cleanup_parser = subparsers.add_parser(
        "cleanup-receipts",
        help="Review or remove finalized receipts past the configured retention period.",
    )
    cleanup_parser.add_argument("--apply", action="store_true", help="Delete eligible private receipt files.")
    cleanup_parser.add_argument("--retention-days", type=int, default=None)
    args = parser.parse_args()
    if args.command == "provision-admin":
        return provision_admin()
    if args.command == "cleanup-receipts":
        return cleanup_receipts(args.apply, args.retention_days)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
