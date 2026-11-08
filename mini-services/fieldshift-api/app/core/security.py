"""Authentication primitives: PBKDF2 password hashing and opaque bearer tokens.

Design notes (see ADR-0004):
- Passwords: PBKDF2-HMAC-SHA256 with per-user random salt (stdlib, no native deps).
- Tokens: 256-bit random opaque tokens; only their SHA-256 hash is stored.
- This is a deliberately small, auditable scheme for the first vertical slice,
  not a full identity platform (no refresh rotation yet — see KNOWN_LIMITATIONS.md).
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from app.core.config import settings

PBKDF2_ITERATIONS = settings.password_pbkdf2_iterations
TOKEN_TTL_SECONDS = settings.auth_token_ttl_seconds
REFRESH_TOKEN_TTL_SECONDS = settings.auth_refresh_ttl_seconds


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def generate_token(ttl_seconds: int | None = None) -> tuple[str, str, datetime]:
    """Return (plaintext_token, token_hash, expires_at).

    `ttl_seconds` defaults to the access-token TTL (TOKEN_TTL_SECONDS).
    """
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    ttl = TOKEN_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
    return token, token_hash, expires_at


def generate_refresh_token() -> tuple[str, str, datetime]:
    """Return (plaintext_token, token_hash, expires_at) with the refresh TTL."""
    return generate_token(ttl_seconds=REFRESH_TOKEN_TTL_SECONDS)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
