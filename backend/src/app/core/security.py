"""Security utilities for password hashing and verification."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.redis import redis_client

settings = get_settings()
ALGORITHM = "HS256"
DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours for MVP usability

# In-memory fallback for environments/tests where Redis is unavailable
_REVOKED_JTIS_LOCAL: set[str] = set()


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Generate a signed cryptographic JWT access token."""
    to_encode = data.copy()
    now = datetime.now(UTC)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES)
    if "jti" not in to_encode:
        to_encode["jti"] = str(uuid.uuid4())
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT access token. Returns payload dict or None if invalid."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except (jwt.PyJWTError, ValueError):
        return None


async def revoke_access_token(payload: dict[str, Any]) -> None:
    """Revoke a decoded JWT access token by its jti until its expiration."""
    jti = payload.get("jti")
    if not jti:
        return
    _REVOKED_JTIS_LOCAL.add(str(jti))
    exp = payload.get("exp")
    ttl = DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    if isinstance(exp, (int, float)):
        ttl = max(1, int(exp - datetime.now(UTC).timestamp()))
    try:
        await redis_client.setex(f"revoked_jti:{jti}", ttl, "1")
    except Exception:
        pass


async def is_token_revoked(payload: dict[str, Any]) -> bool:
    """Check whether a decoded JWT access token has been revoked."""
    jti = payload.get("jti")
    if not jti:
        return False
    if str(jti) in _REVOKED_JTIS_LOCAL:
        return True
    try:
        return bool(await redis_client.exists(f"revoked_jti:{jti}"))
    except Exception:
        return False


def hash_password(password: str, rounds: int = 12) -> str:
    """Hash a plaintext password securely using bcrypt with work factor >= 12.

    Cost factor defaults to 12 as required by the database and security specification.
    Never stores or persists plaintext passwords.
    """
    if not password:
        raise ValueError("Password cannot be empty.")
    if len(password) > 128:
        raise ValueError("Password exceeds maximum allowed length of 128 characters.")
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False
