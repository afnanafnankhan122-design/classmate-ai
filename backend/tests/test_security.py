import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.security import (
    decrypt_google_token,
    encrypt_google_token,
    validate_google_token_encryption_key,
)


class SecurityEncryptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fernet_key = Fernet.generate_key().decode("ascii")

    def test_encrypt_and_decrypt_token_roundtrip(self) -> None:
        raw_token = "mock-sample-google-oauth-access-token-1234567890"
        with patch.object(settings, "google_token_encryption_key", self.fernet_key):
            validate_google_token_encryption_key()
            encrypted = encrypt_google_token(raw_token)
            self.assertNotEqual(encrypted, raw_token)
            decrypted = decrypt_google_token(encrypted)
            self.assertEqual(decrypted, raw_token)

    def test_missing_encryption_key_raises_runtime_error(self) -> None:
        with patch.object(settings, "google_token_encryption_key", ""):
            with self.assertRaises(RuntimeError) as ctx:
                validate_google_token_encryption_key()
            self.assertIn("not configured", str(ctx.exception))

    def test_invalid_encryption_key_raises_runtime_error(self) -> None:
        with patch.object(settings, "google_token_encryption_key", "not-a-valid-fernet-key"):
            with self.assertRaises(RuntimeError) as ctx:
                validate_google_token_encryption_key()
            self.assertIn("must be a valid Fernet key", str(ctx.exception))

    def test_corrupted_encrypted_token_raises_runtime_error(self) -> None:
        with patch.object(settings, "google_token_encryption_key", self.fernet_key):
            with self.assertRaises(RuntimeError) as ctx:
                decrypt_google_token("invalid-garbage-encrypted-token")
            self.assertIn("could not be decrypted", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

