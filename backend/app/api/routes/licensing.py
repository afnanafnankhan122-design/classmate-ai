from datetime import UTC, datetime
import hashlib
import re
import unicodedata

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import require_admin
from app.api.routes.auth import get_current_user
from app.core.config import settings
from app.core.auth_security import auth_rate_limiter, verify_password
from app.database.dependencies import get_db
from app.models.licensing import (
    License,
    LicenseAuditLog,
    LicensingPolicy,
    Payment,
    PaymentMethod,
    Plan,
)
from app.models.user import User
from app.services.calendar_months import add_calendar_months
from app.services.entitlements import get_license_status
from app.services.receipt_storage import receipt_path, remove_receipt, store_receipt
from app.services.receipt_validation import validate_receipt_image

router = APIRouter(tags=["payments and licensing"])
_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{2,127}$")
_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_MAX_REQUEST_OVERHEAD = 256 * 1024


class Reauthentication(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class PaymentMethodUpdate(Reauthentication):
    name: str = Field(min_length=2, max_length=120)
    account_holder_name: str | None = Field(default=None, max_length=255)
    account_number: str | None = Field(default=None, max_length=100)
    instructions: str | None = Field(default=None, max_length=4000)
    is_enabled: bool = False
    confirm_details_verified: bool = False


class PaymentDecision(Reauthentication):
    pass


class PaymentRejection(PaymentDecision):
    reason: str = Field(min_length=3, max_length=2000)


class PaymentRefund(PaymentDecision):
    reason: str = Field(min_length=3, max_length=2000)


class LicensingPolicyUpdate(Reauthentication):
    launch_at: datetime
    grandfathering_days: int = Field(ge=1, le=365)

    @model_validator(mode="after")
    def require_timezone(self) -> "LicensingPolicyUpdate":
        if self.launch_at.tzinfo is None or self.launch_at.utcoffset() is None:
            raise ValueError("launch_at must include a timezone.")
        return self


def _reauthenticate(admin: User, password: str) -> None:
    key = f"licensing-admin-reauth:{admin.id}"
    if not auth_rate_limiter.is_allowed(key, max_attempts=5, window_seconds=900):
        raise HTTPException(
            status_code=429,
            detail="Too many administrator reauthentication attempts. Try again later.",
        )
    if not admin.hashed_password or not verify_password(password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="Administrator reauthentication failed.")
    auth_rate_limiter.reset(key)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _payment_dict(payment: Payment, include_student: bool = False) -> dict:
    result = {
        "id": payment.id,
        "status": payment.status,
        "amount_paisa": payment.amount_paisa,
        "currency": payment.currency,
        "duration_months": payment.duration_months,
        "payment_method": payment.payment_method.name if payment.payment_method else None,
        "transaction_reference": payment.transaction_reference,
        "submitted_at": payment.submitted_at.isoformat() if payment.submitted_at else None,
        "reviewed_at": payment.reviewed_at.isoformat() if payment.reviewed_at else None,
        "rejection_reason": payment.rejection_reason,
        "receipt_available": payment.receipt_storage_key is not None,
        "license_started_at": (
            payment.license_started_at.isoformat() if payment.license_started_at else None
        ),
        "license_expires_at": (
            payment.license_expires_at.isoformat() if payment.license_expires_at else None
        ),
        "refunded_at": payment.refunded_at.isoformat() if payment.refunded_at else None,
        "refund_reason": payment.refund_reason,
    }
    if include_student and payment.user:
        result["student"] = {
            "id": payment.user.id,
            "full_name": payment.user.full_name,
            "email": payment.user.email,
        }
    return result


def _license_status_dict(db: Session, user: User) -> dict:
    status = get_license_status(db, user)
    return {
        "status": status.status,
        "active": status.active,
        "source": status.source,
        "starts_at": status.starts_at.isoformat() if status.starts_at else None,
        "expires_at": status.expires_at.isoformat() if status.expires_at else None,
        "reason": status.reason,
    }


def _normalize_reference(value: str) -> tuple[str, str]:
    reference = unicodedata.normalize("NFKC", value).strip()
    if _REFERENCE_PATTERN.fullmatch(reference) is None:
        raise HTTPException(
            status_code=422,
            detail="Enter a transaction reference containing 3-128 letters, digits, or . _ / - characters.",
        )
    return reference, reference.casefold()


def _check_request_size(request: Request) -> None:
    raw_length = request.headers.get("content-length")
    if raw_length is None:
        raise HTTPException(
            status_code=411,
            detail="A Content-Length header is required for receipt uploads.",
        )
    try:
        request_length = int(raw_length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from exc
    if request_length > settings.payment_receipt_max_bytes + _MAX_REQUEST_OVERHEAD:
        raise HTTPException(status_code=413, detail="Receipt upload exceeds the 5 MiB limit.")


def _conflict_after_integrity_error(
    db: Session,
    user_id: int,
    idempotency_key: str | None,
    fingerprint: str,
) -> Payment | None:
    if idempotency_key:
        existing = db.scalar(
            select(Payment)
            .options(joinedload(Payment.payment_method))
            .where(Payment.user_id == user_id, Payment.idempotency_key == idempotency_key)
        )
        if existing:
            if existing.submission_fingerprint == fingerprint:
                return existing
            raise HTTPException(
                status_code=409,
                detail="This idempotency key was already used for a different payment submission.",
            )
    pending = db.scalar(
        select(Payment).where(Payment.user_id == user_id, Payment.status == "pending")
    )
    if pending:
        raise HTTPException(
            status_code=409,
            detail="You already have a payment awaiting verification.",
        )
    raise HTTPException(
        status_code=409,
        detail="The payment reference has already been submitted. Verify the reference and try again.",
    )


async def _submit_payment(
    request: Request,
    response: Response,
    payment_method_id: int,
    transaction_reference: str,
    receipt: UploadFile,
    idempotency_key: str | None,
    db: Session,
    user: User,
) -> dict:
    _check_request_size(request)
    reference, normalized_reference = _normalize_reference(transaction_reference)
    if idempotency_key and _IDEMPOTENCY_PATTERN.fullmatch(idempotency_key) is None:
        raise HTTPException(status_code=422, detail="Invalid Idempotency-Key header.")

    method = db.get(PaymentMethod, payment_method_id)
    if (
        method is None
        or not method.is_enabled
        or method.details_verified_at is None
        or method.details_verified_by_user_id is None
    ):
        raise HTTPException(status_code=404, detail="Payment method is unavailable.")
    plan = db.scalar(select(Plan).where(Plan.code == "semester", Plan.is_enabled.is_(True)))
    if plan is None:
        raise HTTPException(status_code=503, detail="Semester payment plan is not configured.")

    content = bytearray()
    while True:
        chunk = await receipt.read(64 * 1024)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > settings.payment_receipt_max_bytes:
            raise HTTPException(status_code=413, detail="Receipt upload exceeds the 5 MiB limit.")
    try:
        extension, content_type = validate_receipt_image(
            bytes(content),
            receipt.filename,
            receipt.content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await receipt.close()

    fingerprint = hashlib.sha256(
        f"{method.id}:{normalized_reference}:".encode("utf-8") + bytes(content)
    ).hexdigest()
    if idempotency_key:
        existing = db.scalar(
            select(Payment)
            .options(joinedload(Payment.payment_method))
            .where(Payment.user_id == user.id, Payment.idempotency_key == idempotency_key)
        )
        if existing:
            if existing.submission_fingerprint != fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail="This idempotency key was already used for a different payment submission.",
                )
            response.status_code = 200
            return _payment_dict(existing)

    pending = db.scalar(
        select(Payment).where(Payment.user_id == user.id, Payment.status == "pending")
    )
    if pending is not None:
        raise HTTPException(
            status_code=409,
            detail="You already have a payment awaiting verification.",
        )
    duplicate_reference = db.scalar(
        select(Payment.id).where(
            Payment.payment_method_id == method.id,
            Payment.transaction_reference_normalized == normalized_reference,
        )
    )
    if duplicate_reference is not None:
        raise HTTPException(
            status_code=409,
            detail="This transaction reference has already been submitted.",
        )

    try:
        storage_key = store_receipt(bytes(content), extension)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Private receipt storage is unavailable. Please try again later.",
        ) from exc

    previous_rejection = db.scalar(
        select(Payment)
        .where(Payment.user_id == user.id, Payment.status == "rejected")
        .order_by(Payment.reviewed_at.desc(), Payment.id.desc())
        .limit(1)
    )
    payment = Payment(
        user_id=user.id,
        payment_method_id=method.id,
        plan_id=plan.id,
        status="pending",
        amount_paisa=plan.amount_paisa,
        currency=plan.currency,
        duration_months=plan.duration_months,
        transaction_reference=reference,
        transaction_reference_normalized=normalized_reference,
        receipt_storage_key=storage_key,
        receipt_content_type=content_type,
        receipt_size=len(content),
        idempotency_key=idempotency_key,
        submission_fingerprint=fingerprint,
        resubmission_of_id=previous_rejection.id if previous_rejection else None,
    )
    db.add(payment)
    try:
        db.flush()
        db.add(
            LicenseAuditLog(
                user_id=user.id,
                payment_id=payment.id,
                actor_user_id=user.id,
                action="payment_submitted",
                details={"payment_method": method.code, "amount_paisa": plan.amount_paisa},
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        try:
            remove_receipt(storage_key)
        except OSError:
            raise HTTPException(
                status_code=503,
                detail="A payment submission conflict occurred and receipt cleanup failed. Contact support.",
            ) from exc
        return _payment_dict(
            _conflict_after_integrity_error(db, user.id, idempotency_key, fingerprint)
        )
    except SQLAlchemyError as exc:
        db.rollback()
        try:
            remove_receipt(storage_key)
        except OSError:
            raise HTTPException(
                status_code=503,
                detail="Payment storage failed and receipt cleanup failed. Contact support.",
            ) from exc
        raise HTTPException(
            status_code=503,
            detail="Payment storage is temporarily unavailable.",
        ) from exc
    response.status_code = 201
    return _payment_dict(payment)


@router.get("/plans")
def list_plans(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    plans = db.scalars(select(Plan).where(Plan.is_enabled.is_(True)).order_by(Plan.id)).all()
    return {
        "plans": [
            {
                "id": plan.id,
                "code": plan.code,
                "name": plan.name,
                "amount_paisa": plan.amount_paisa,
                "amount_pkr": plan.amount_paisa / 100,
                "currency": plan.currency,
                "duration_months": plan.duration_months,
            }
            for plan in plans
        ]
    }


@router.get("/payments/methods")
def list_payment_methods(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    methods = db.scalars(
        select(PaymentMethod)
        .where(
            PaymentMethod.is_enabled.is_(True),
            PaymentMethod.details_verified_at.is_not(None),
            PaymentMethod.details_verified_by_user_id.is_not(None),
        )
        .order_by(PaymentMethod.id)
    ).all()
    return {
        "payment_methods": [
            {
                "id": method.id,
                "code": method.code,
                "name": method.name,
                "account_holder_name": method.account_holder_name,
                "account_number": method.account_number,
                "instructions": method.instructions,
            }
            for method in methods
        ]
    }


@router.post("/payments/submit", status_code=201)
async def submit_payment(
    request: Request,
    response: Response,
    payment_method_id: int = Form(...),
    transaction_reference: str = Form(..., max_length=128),
    receipt: UploadFile = File(...),
    idempotency_key: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    header_key = request.headers.get("Idempotency-Key")
    if header_key and idempotency_key and header_key != idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency key header and form value must match.")
    return await _submit_payment(
        request,
        response,
        payment_method_id,
        transaction_reference,
        receipt,
        header_key or idempotency_key,
        db,
        user,
    )


@router.post("/licenses/renew", status_code=201)
async def submit_renewal(
    request: Request,
    response: Response,
    payment_method_id: int = Form(...),
    transaction_reference: str = Form(..., max_length=128),
    receipt: UploadFile = File(...),
    idempotency_key: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    header_key = request.headers.get("Idempotency-Key")
    if header_key and idempotency_key and header_key != idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency key header and form value must match.")
    return await _submit_payment(
        request,
        response,
        payment_method_id,
        transaction_reference,
        receipt,
        header_key or idempotency_key,
        db,
        user,
    )


@router.get("/payments/my")
def list_my_payments(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    payments = db.scalars(
        select(Payment)
        .options(joinedload(Payment.payment_method))
        .where(Payment.user_id == user.id)
        .order_by(Payment.submitted_at.desc(), Payment.id.desc())
    ).all()
    return {"payments": [_payment_dict(payment) for payment in payments]}


@router.get("/payments/{payment_id}/receipt")
def get_payment_receipt(
    payment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    payment = db.get(Payment, payment_id)
    if payment is None or (payment.user_id != user.id and not user.is_admin):
        raise HTTPException(status_code=404, detail="Receipt not found.")
    try:
        path = receipt_path(payment.receipt_storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Receipt not found.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Receipt not found.")
    media_type = payment.receipt_content_type or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename="payment-receipt")


@router.get("/licenses/my")
def get_my_license(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return {"license": _license_status_dict(db, user)}


@router.get("/licenses/status")
def get_my_license_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return _license_status_dict(db, user)


@router.get("/admin/access")
def get_admin_access(user: User = Depends(get_current_user)) -> dict:
    return {"is_admin": user.is_admin}


@router.get("/admin/payment-methods")
def admin_list_payment_methods(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    methods = db.scalars(select(PaymentMethod).order_by(PaymentMethod.id)).all()
    return {
        "payment_methods": [
            {
                "id": method.id,
                "code": method.code,
                "name": method.name,
                "account_holder_name": method.account_holder_name,
                "account_number": method.account_number,
                "instructions": method.instructions,
                "is_enabled": method.is_enabled,
                "details_verified_at": (
                    method.details_verified_at.isoformat() if method.details_verified_at else None
                ),
            }
            for method in methods
        ]
    }


@router.patch("/admin/payment-methods/{method_id}")
def update_payment_method(
    method_id: int,
    body: PaymentMethodUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    _reauthenticate(admin, body.password)
    method = db.get(PaymentMethod, method_id)
    if method is None:
        raise HTTPException(status_code=404, detail="Payment method not found.")
    if len(body.name.strip()) < 2:
        raise HTTPException(status_code=422, detail="Payment method name must be at least 2 characters.")
    if body.is_enabled and not body.confirm_details_verified:
        raise HTTPException(
            status_code=422,
            detail="Confirm that the payment details were independently verified before enabling this method.",
        )
    if body.is_enabled and not all(
        [
            (body.account_holder_name or "").strip(),
            (body.account_number or "").strip(),
            (body.instructions or "").strip(),
        ]
    ):
        raise HTTPException(
            status_code=422,
            detail="Account holder name, account number, and payment instructions are required to enable this method.",
        )
    method.name = body.name.strip()
    method.account_holder_name = (
        body.account_holder_name.strip() if body.account_holder_name else None
    )
    method.account_number = body.account_number.strip() if body.account_number else None
    method.instructions = body.instructions.strip() if body.instructions else None
    method.is_enabled = body.is_enabled
    method.details_verified_at = datetime.now(UTC) if body.is_enabled else None
    method.details_verified_by_user_id = admin.id if body.is_enabled else None
    method.updated_at = datetime.now(UTC)
    db.add(
        LicenseAuditLog(
            actor_user_id=admin.id,
            action="payment_method_updated",
            details={
                "method_code": method.code,
                "is_enabled": method.is_enabled,
                "details_verified": method.details_verified_at is not None,
            },
        )
    )
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Payment method update could not be saved.") from exc
    return {"payment_method": {"id": method.id, "code": method.code, "is_enabled": method.is_enabled}}


@router.get("/admin/payments")
def admin_list_payments(
    status: str = "pending",
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    if status not in {"pending", "approved", "rejected", "all"}:
        raise HTTPException(status_code=422, detail="Status must be pending, approved, rejected, or all.")
    statement = (
        select(Payment)
        .options(joinedload(Payment.payment_method), joinedload(Payment.user))
        .order_by(Payment.submitted_at.asc(), Payment.id.asc())
        .limit(500)
    )
    if status != "all":
        statement = statement.where(Payment.status == status)
    payments = db.scalars(statement).unique().all()
    return {"payments": [_payment_dict(payment, include_student=True) for payment in payments]}


@router.post("/admin/payments/{payment_id}/approve")
def approve_payment(
    payment_id: int,
    body: Reauthentication,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    _reauthenticate(admin, body.password)
    payment = db.scalar(
        select(Payment)
        .options(joinedload(Payment.payment_method))
        .where(Payment.id == payment_id)
        .with_for_update()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if payment.status == "approved":
        return {"payment": _payment_dict(payment), "already_approved": True}
    if payment.status != "pending":
        raise HTTPException(status_code=409, detail="Only pending payments can be approved.")

    now = datetime.now(UTC)
    result = db.execute(
        update(Payment)
        .where(Payment.id == payment.id, Payment.status == "pending")
        .values(status="approved", reviewed_at=now, reviewed_by_user_id=admin.id)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        current = db.get(Payment, payment_id)
        if current is not None and current.status == "approved":
            return {"payment": _payment_dict(current), "already_approved": True}
        raise HTTPException(status_code=409, detail="Payment is no longer pending.")

    db.refresh(payment)
    license_record = db.scalar(
        select(License)
        .where(License.user_id == payment.user_id)
        .with_for_update()
    )
    if (
        license_record is not None
        and license_record.revoked_at is None
        and _utc(license_record.expires_at) > now
    ):
        term_start = _utc(license_record.starts_at)
        term_end = add_calendar_months(_utc(license_record.expires_at), payment.duration_months)
    else:
        term_start = now
        term_end = add_calendar_months(now, payment.duration_months)

    if license_record is None:
        license_record = License(
            user_id=payment.user_id,
            plan_id=payment.plan_id,
            starts_at=term_start,
            expires_at=term_end,
            last_approved_payment_id=payment.id,
        )
        db.add(license_record)
        db.flush()
    else:
        license_record.plan_id = payment.plan_id
        license_record.starts_at = term_start
        license_record.expires_at = term_end
        license_record.last_approved_payment_id = payment.id
        license_record.revoked_at = None
        license_record.revoked_by_user_id = None
        license_record.revocation_reason = None
        license_record.updated_at = now

    payment.license_started_at = term_start
    payment.license_expires_at = term_end
    db.add(
        LicenseAuditLog(
            user_id=payment.user_id,
            payment_id=payment.id,
            license_id=license_record.id,
            actor_user_id=admin.id,
            action="payment_approved",
            details={
                "license_started_at": term_start.isoformat(),
                "license_expires_at": term_end.isoformat(),
                "renewal_extended_from_existing_expiry": term_start != now,
            },
        )
    )
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Payment approval could not be committed.") from exc
    return {"payment": _payment_dict(payment), "already_approved": False}


@router.post("/admin/payments/{payment_id}/reject")
def reject_payment(
    payment_id: int,
    body: PaymentRejection,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    _reauthenticate(admin, body.password)
    reason = body.reason.strip()
    if len(reason) < 3:
        raise HTTPException(status_code=422, detail="A rejection reason of at least 3 characters is required.")
    payment = db.scalar(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if payment.status == "rejected":
        return {"payment": _payment_dict(payment), "already_rejected": True}
    if payment.status != "pending":
        raise HTTPException(status_code=409, detail="Only pending payments can be rejected.")

    now = datetime.now(UTC)
    result = db.execute(
        update(Payment)
        .where(Payment.id == payment.id, Payment.status == "pending")
        .values(
            status="rejected",
            reviewed_at=now,
            reviewed_by_user_id=admin.id,
            rejection_reason=reason,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Payment is no longer pending.")
    db.refresh(payment)
    db.add(
        LicenseAuditLog(
            user_id=payment.user_id,
            payment_id=payment.id,
            actor_user_id=admin.id,
            action="payment_rejected",
            details={"reason": reason},
        )
    )
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Payment rejection could not be saved.") from exc
    return {"payment": _payment_dict(payment), "already_rejected": False}


@router.post("/admin/payments/{payment_id}/refund")
def refund_payment(
    payment_id: int,
    body: PaymentRefund,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    _reauthenticate(admin, body.password)
    reason = body.reason.strip()
    if len(reason) < 3:
        raise HTTPException(status_code=422, detail="A refund reason of at least 3 characters is required.")
    payment = db.scalar(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if payment.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved payments can be refunded.")
    if payment.refunded_at is not None:
        return {"payment": _payment_dict(payment), "already_refunded": True}

    now = datetime.now(UTC)
    payment.refunded_at = now
    payment.refunded_by_user_id = admin.id
    payment.refund_reason = reason
    license_record = db.scalar(
        select(License)
        .where(License.user_id == payment.user_id)
        .with_for_update()
    )
    revoked_current_license = False
    if (
        license_record is not None
        and license_record.last_approved_payment_id == payment.id
        and license_record.revoked_at is None
    ):
        license_record.revoked_at = now
        license_record.revoked_by_user_id = admin.id
        license_record.revocation_reason = f"Refund: {reason}"
        license_record.updated_at = now
        revoked_current_license = True
    db.add(
        LicenseAuditLog(
            user_id=payment.user_id,
            payment_id=payment.id,
            license_id=license_record.id if license_record else None,
            actor_user_id=admin.id,
            action="payment_refunded",
            details={"reason": reason, "current_license_revoked": revoked_current_license},
        )
    )
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Refund record could not be saved.") from exc
    return {"payment": _payment_dict(payment), "current_license_revoked": revoked_current_license}


@router.get("/admin/licenses")
def admin_list_licenses(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    licenses = db.scalars(
        select(License)
        .options(joinedload(License.user))
        .order_by(License.expires_at.asc())
        .limit(1000)
    ).unique().all()
    now = datetime.now(UTC)
    return {
        "licenses": [
            {
                "user_id": item.user_id,
                "student_name": item.user.full_name,
                "student_email": item.user.email,
                "status": (
                    "revoked"
                    if item.revoked_at is not None
                    else "active"
                    if _utc(item.starts_at) <= now < _utc(item.expires_at)
                    else "expired"
                ),
                "starts_at": item.starts_at.isoformat(),
                "expires_at": item.expires_at.isoformat(),
                "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None,
            }
            for item in licenses
        ]
    }


@router.get("/admin/license-policy")
def get_admin_license_policy(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    policy = db.get(LicensingPolicy, 1)
    if policy is None:
        raise HTTPException(status_code=503, detail="Licensing policy is not initialized.")
    return {
        "launch_at": policy.launch_at.isoformat() if policy.launch_at else None,
        "grandfathering_days": policy.grandfathering_days,
        "locked": bool(policy.launch_at and datetime.now(UTC) >= _utc(policy.launch_at)),
    }


@router.patch("/admin/license-policy")
def update_admin_license_policy(
    body: LicensingPolicyUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    _reauthenticate(admin, body.password)
    now = datetime.now(UTC)
    launch_at = body.launch_at.astimezone(UTC)
    if launch_at < now:
        raise HTTPException(status_code=422, detail="Grandfathering launch time cannot be in the past.")
    policy = db.get(LicensingPolicy, 1)
    if policy is None:
        policy = LicensingPolicy(id=1, grandfathering_days=body.grandfathering_days)
        db.add(policy)
        db.flush()
    if policy.launch_at is not None and now >= _utc(policy.launch_at):
        raise HTTPException(status_code=409, detail="The grandfathering policy is locked after launch.")
    old_launch_at = policy.launch_at.isoformat() if policy.launch_at else None
    old_days = policy.grandfathering_days
    policy.launch_at = launch_at
    policy.grandfathering_days = body.grandfathering_days
    policy.configured_at = now
    policy.configured_by_user_id = admin.id
    db.add(
        LicenseAuditLog(
            actor_user_id=admin.id,
            action="grandfathering_policy_configured",
            details={
                "previous_launch_at": old_launch_at,
                "launch_at": launch_at.isoformat(),
                "previous_grandfathering_days": old_days,
                "grandfathering_days": body.grandfathering_days,
            },
        )
    )
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Licensing policy could not be saved.") from exc
    return {
        "launch_at": policy.launch_at.isoformat(),
        "grandfathering_days": policy.grandfathering_days,
        "locked": now >= launch_at,
    }


@router.get("/admin/audit-logs")
def list_license_audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 500.")
    entries = db.scalars(
        select(LicenseAuditLog)
        .options(joinedload(LicenseAuditLog.actor))
        .order_by(LicenseAuditLog.created_at.desc(), LicenseAuditLog.id.desc())
        .limit(limit)
    ).unique().all()
    return {
        "audit_logs": [
            {
                "id": item.id,
                "user_id": item.user_id,
                "payment_id": item.payment_id,
                "license_id": item.license_id,
                "actor": item.actor.email if item.actor else None,
                "action": item.action,
                "details": item.details,
                "created_at": item.created_at.isoformat(),
            }
            for item in entries
        ]
    }
