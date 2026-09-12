"""Password hashing and JWT tokens.

Passwords use PBKDF2-HMAC-SHA256 from the standard library rather than bcrypt:
bcrypt ships a compiled extension, and this machine's Smart App Control blocks
compiled extensions without an established reputation. PBKDF2 with a per-user
salt and a high iteration count is an accepted choice (NIST SP 800-63B).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from backend.app.settings import get_settings


def hash_password(password: str) -> str:
    """Return ``pbkdf2_sha256$iterations$salt$digest``, all base64 where binary."""
    iterations = int(get_settings().api["auth"]["pbkdf2_iterations"])
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of a password against a stored hash."""
    try:
        scheme, iterations, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(digest_b64)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(actual, expected)


def create_token(subject: str, role: str, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(minutes=int(settings.api["auth"]["token_minutes"]))).timestamp()
        ),
    }
    if extra:
        claims.update(extra)
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.api["auth"]["algorithm"])


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a token. Raises ``jwt.PyJWTError`` on any failure."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.api["auth"]["algorithm"]])
