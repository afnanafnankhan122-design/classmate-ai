import unittest
import secrets

from pydantic import ValidationError

from app.core.config import Settings


class ProductionConfigurationTests(unittest.TestCase):
    def test_production_rejects_sample_and_short_session_secrets(self) -> None:
        for secret in (
            "change-me-in-production",
            "replace-with-a-secure-random-secret-key",
            "too-short",
        ):
            with self.subTest(secret=secret):
                with self.assertRaises(ValidationError):
                    Settings(
                        _env_file=None,
                        environment="production",
                        secret_key=secret,
                    )

    def test_production_accepts_a_generated_session_secret(self) -> None:
        settings = Settings(
            _env_file=None,
            environment="production",
            secret_key=secrets.token_urlsafe(32),
        )
        self.assertEqual(settings.environment, "production")


if __name__ == "__main__":
    unittest.main()
