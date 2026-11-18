import os
import re
import uuid
from pathlib import Path

from app.core.config import BACKEND_DIR, settings

_RECEIPT_KEY = re.compile(r"^[0-9a-f]{32}\.(?:jpg|jpeg|png)$")


def _private_root() -> Path:
    root = settings.payment_receipt_dir.resolve()
    public_roots = (
        (BACKEND_DIR / "static").resolve(),
        (BACKEND_DIR.parent / "frontend" / "public").resolve(),
    )
    for public_root in public_roots:
        try:
            root.relative_to(public_root)
        except ValueError:
            continue
        raise RuntimeError("Payment receipt storage cannot be inside a public assets directory.")
    return root


def store_receipt(content: bytes, extension: str) -> str:
    if extension not in {"jpg", "jpeg", "png"}:
        raise ValueError("Unsupported receipt extension.")
    root = _private_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = f"{uuid.uuid4().hex}.{extension}"
    destination = root / key
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
    except OSError:
        destination.unlink(missing_ok=True)
        raise
    return key


def receipt_path(key: str | None) -> Path:
    if key is None or _RECEIPT_KEY.fullmatch(key) is None:
        raise FileNotFoundError("Receipt not found.")
    root = _private_root()
    path = (root / key).resolve()
    if path.parent != root:
        raise FileNotFoundError("Receipt not found.")
    return path


def remove_receipt(key: str | None) -> None:
    if key is None:
        return
    receipt_path(key).unlink(missing_ok=True)


def quarantine_receipt(key: str | None) -> bool:
    if key is None:
        return False
    source = receipt_path(key)
    quarantine = source.with_name(f"{key}.deleting")
    if quarantine.is_file():
        return True
    if not source.is_file():
        return False
    os.replace(source, quarantine)
    return True


def restore_quarantined_receipt(key: str | None) -> None:
    if key is None:
        return
    source = receipt_path(key)
    quarantine = source.with_name(f"{key}.deleting")
    if quarantine.is_file():
        os.replace(quarantine, source)


def delete_quarantined_receipt(key: str | None) -> None:
    if key is None:
        return
    source = receipt_path(key)
    source.with_name(f"{key}.deleting").unlink(missing_ok=True)
