from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _token_cipher() -> Fernet:
    if not settings.google_token_encryption_key:
        raise RuntimeError("GOOGLE_TOKEN_ENCRYPTION_KEY is not configured.")
    try:
        return Fernet(settings.google_token_encryption_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("GOOGLE_TOKEN_ENCRYPTION_KEY must be a valid Fernet key.") from exc


def validate_google_token_encryption_key() -> None:
    _token_cipher()


def encrypt_google_token(token: str) -> str:
    return _token_cipher().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_google_token(encrypted_token: str) -> str:
    try:
        return _token_cipher().decrypt(encrypted_token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("Stored Google token could not be decrypted.") from exc
