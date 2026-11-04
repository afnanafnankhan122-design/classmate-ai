"""Safe environment and OAuth diagnostic tool for ClassMate AI.

This script never prints or exposes secrets or sensitive credential values.
It reports only whether required configuration is present and valid.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

# Ensure backend root is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def run_diagnostics() -> int:
    print("=" * 60)
    print("ClassMate AI - Google OAuth Environment Diagnostics")
    print("=" * 60)

    # 1. python-dotenv check
    try:
        import dotenv
        print(f"[OK] python-dotenv is installed (location: {dotenv.__file__})")
    except ImportError:
        print("[FAIL] python-dotenv is NOT installed.")
        return 1

    # 2. backend/.env path check
    env_path = BACKEND_DIR / ".env"
    print(f"\nTarget .env path: {env_path}")
    if env_path.is_file():
        print(f"[OK] backend/.env file exists ({env_path.stat().st_size} bytes)")
    else:
        print(f"[FAIL] backend/.env file does not exist at {env_path}")
        return 1

    # 3. Check variable names matching in .env
    target_vars = [
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_TOKEN_ENCRYPTION_KEY",
    ]
    raw_env_keys: dict[str, int] = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            clean = line.strip()
            if not clean or clean.startswith("#") or "=" not in clean:
                continue
            k, v = clean.split("=", 1)
            raw_env_keys[k.strip()] = len(v.strip())

    print("\nVariable matching in backend/.env:")
    all_matched = True
    for var in target_vars:
        if var in raw_env_keys:
            val_len = raw_env_keys[var]
            if val_len > 0:
                print(f"  [OK] {var}: present and populated ({val_len} characters)")
            else:
                print(f"  [FAIL] {var}: present but EMPTY (0 characters)")
                all_matched = False
        else:
            print(f"  [FAIL] {var}: NOT found in .env file")
            all_matched = False

    # 4. Check for process environment overrides
    print("\nProcess environment (os.environ) overrides:")
    overrides_found = False
    for var in target_vars:
        if var in os.environ:
            val = os.environ[var]
            print(f"  [NOTICE] os.environ[{var}] is set (length: {len(val)})")
            overrides_found = True
        else:
            print(f"  [OK] os.environ[{var}] is not set (no external override)")
    if not overrides_found:
        print("  [OK] No environment variables are overriding the .env file.")

    # 5. Check app.core.config settings loader
    print("\nApp Settings loader check:")
    try:
        from app.core.config import get_settings, settings
        s = get_settings()
        cid_ok = bool(s.google_client_id.strip())
        csec_ok = bool(s.google_client_secret.strip())
        key_ok = bool(s.google_token_encryption_key.strip())
        print(f"  settings.google_client_id populated: {cid_ok}")
        print(f"  settings.google_client_secret populated: {csec_ok}")
        print(f"  settings.google_token_encryption_key populated: {key_ok}")
        print(f"  settings.google_redirect_uri: {s.google_redirect_uri}")
    except Exception as exc:
        print(f"  [FAIL] Failed to load settings: {exc}")
        return 1

    # 6. Fernet encryption key validation
    print("\nToken encryption key check:")
    try:
        from app.core.security import validate_google_token_encryption_key
        validate_google_token_encryption_key()
        print("  [OK] GOOGLE_TOKEN_ENCRYPTION_KEY is a valid Fernet key.")
    except Exception as exc:
        print(f"  [FAIL] GOOGLE_TOKEN_ENCRYPTION_KEY validation error: {exc}")
        return 1

    # 7. OAuth Flow initialization
    print("\nOAuth Flow initialization check:")
    try:
        from app.services.google_oauth import create_oauth_flow
        flow = create_oauth_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        print("  [OK] OAuth Flow generated authorization URL successfully.")
        print(f"  [OK] Authorization URL host: {auth_url.split('?')[0]}")
        print(f"  [OK] State parameter generated: {bool(state)}")
    except Exception as exc:
        print(f"  [FAIL] OAuth Flow creation failed: {exc}")
        return 1

    print("\n" + "=" * 60)
    print("RESULT: All Google OAuth checks passed successfully!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(run_diagnostics())

