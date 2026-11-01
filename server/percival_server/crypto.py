"""Encryption for secrets we keep in the database (broker/redis URLs)."""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from percival.naming import NAME


class SecretBox:
    def __init__(self, secret_key: str) -> None:
        # derive instead of using the env value directly, so the same secret
        # can feed other purposes later without key reuse
        raw = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=f"{NAME}-fernet-v1".encode(),
        ).derive(secret_key.encode())
        self._fernet = Fernet(base64.urlsafe_b64encode(raw))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("can't decrypt a stored secret, was the SECRET_KEY changed?") from exc
