"""AES-256-GCM encryption for Plaid access tokens.

Decrypted access tokens exist only inside the Plaid client call boundary; the
database stores base64 ciphertext, a per-encryption nonce, and the key version
that was used, which is also authenticated as associated data.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
NONCE_BYTES = 12


@dataclass(frozen=True)
class EncryptedSecret:
    """A stored secret: URL-safe base64 ciphertext plus its nonce and key version."""

    ciphertext: str
    nonce: str
    key_version: int


class TokenCipher:
    """Encrypts and decrypts secrets with one versioned 32-byte key."""

    def __init__(self, key: bytes, key_version: int) -> None:
        if len(key) != KEY_BYTES:
            raise ValueError(
                f"token encryption key must be {KEY_BYTES} bytes, got {len(key)}"
            )
        if key_version < 1:
            raise ValueError("key_version must be >= 1")
        self._aesgcm = AESGCM(key)
        self._key_version = key_version

    @classmethod
    def from_base64_key(cls, key: str, key_version: int) -> TokenCipher:
        try:
            raw = base64.urlsafe_b64decode(_pad(key))
        except (ValueError, TypeError) as error:
            raise ValueError("token encryption key is not valid base64") from error
        return cls(raw, key_version)

    @property
    def key_version(self) -> int:
        return self._key_version

    def encrypt(self, value: str) -> EncryptedSecret:
        import os

        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self._aesgcm.encrypt(
            nonce, value.encode("utf-8"), self._associated_data(self._key_version)
        )
        return EncryptedSecret(
            ciphertext=_b64(ciphertext),
            nonce=_b64(nonce),
            key_version=self._key_version,
        )

    def decrypt(self, secret: EncryptedSecret) -> str:
        if secret.key_version != self._key_version:
            raise ValueError(
                "encrypted secret was written with key version "
                f"{secret.key_version}; the configured key is version "
                f"{self._key_version}"
            )
        try:
            nonce = base64.urlsafe_b64decode(_pad(secret.nonce))
            ciphertext = base64.urlsafe_b64decode(_pad(secret.ciphertext))
            plaintext = self._aesgcm.decrypt(
                nonce, ciphertext, self._associated_data(secret.key_version)
            )
        except (InvalidTag, ValueError, TypeError) as error:
            raise ValueError("encrypted secret could not be decrypted") from error
        return plaintext.decode("utf-8")

    @staticmethod
    def _associated_data(key_version: int) -> bytes:
        return f"plaid-access-token:v{key_version}".encode("ascii")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _pad(value: str) -> str:
    return value + "=" * (-len(value) % 4)


__all__ = ["EncryptedSecret", "TokenCipher", "KEY_BYTES", "NONCE_BYTES"]
