import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from packages.platform_core.settings import Settings

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


def issue_token_pair(user_id: uuid.UUID, settings: Settings) -> TokenPair:
    now = datetime.now(UTC)
    access_expires_at = now + timedelta(minutes=settings.access_token_ttl_minutes)
    refresh_expires_at = now + timedelta(days=settings.refresh_token_ttl_days)
    access_token = jwt.encode(
        {
            "sub": str(user_id),
            "type": "access",
            "iat": now,
            "exp": access_expires_at,
            "jti": secrets.token_hex(16),
        },
        settings.app_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    return TokenPair(access_token, secrets.token_urlsafe(48), access_expires_at, refresh_expires_at)


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    payload = jwt.decode(
        token,
        settings.app_secret_key.get_secret_value(),
        algorithms=["HS256"],
        options={"require": ["sub", "type", "exp", "iat", "jti"]},
    )
    if payload["type"] != "access":
        raise jwt.InvalidTokenError("Unexpected token type")
    return uuid.UUID(payload["sub"])
