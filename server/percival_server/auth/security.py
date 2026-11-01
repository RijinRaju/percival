"""Password hashing and opaque token helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from percival.naming import NAME

_hasher = PasswordHasher()

# api tokens look like perc_xxxxxxxx..., the prefix makes them greppable in
# leaked-secret scanners and in our own logs
TOKEN_PREFIX = f"{NAME[:4]}_"

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"password needs at least {MIN_PASSWORD_LENGTH} characters"
    return None


def new_secret(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_api_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # tokens are long and random, a fast hash is fine here (unlike passwords)
    return hashlib.sha256(token.encode()).hexdigest()


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
