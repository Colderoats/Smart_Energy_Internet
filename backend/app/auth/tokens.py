"""
Access tokens (short-lived JWT) and opaque random tokens (refresh tokens,
invites). Opaque tokens are only ever stored as SHA-256 hashes; the raw value
exists only in the cookie / invite link.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

ACCESS_COOKIE = "sei_access"
REFRESH_COOKIE = "sei_refresh"
# The refresh cookie is only sent to /auth/* so it never travels with data requests.
REFRESH_COOKIE_PATH = "/auth"


def check_config() -> None:
    if len(settings.jwt_secret) < 32:
        raise RuntimeError(
            "JWT_SECRET is missing or shorter than 32 characters. Set it in the repo-root .env, e.g. "
            "JWT_SECRET=$(python -c \"import secrets; print(secrets.token_urlsafe(48))\")"
        )


def now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user: dict) -> tuple[str, datetime]:
    issued = now()
    expires = issued + timedelta(minutes=settings.access_token_minutes)
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user["role"],
        "type": "access",
        "iat": issued,
        "exp": expires,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires


def decode_access_token(token: str) -> dict | None:
    """Claims of a valid, unexpired access token, else None."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "type"]},
        )
    except jwt.PyJWTError:
        return None
    if claims.get("type") != "access":
        return None
    return claims


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
