"""Re-encrypt stored Plaid access tokens under a new key version.

Ciphertext is bound by AES-GCM associated data to both the key version and the
connection row that owns it, so rotation is a per-row decrypt/re-encrypt. The
whole rotation runs in one transaction: if any row fails to decrypt, nothing
is written and the old key remains the working key.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BankConnection
from app.services.crypto import EncryptedSecret, TokenCipher

logger = logging.getLogger(__name__)


class RotationError(Exception):
    """Raised when rotation cannot complete safely."""


async def rotate_token_encryption_key(
    session: AsyncSession, current: TokenCipher, replacement: TokenCipher
) -> int:
    """Re-encrypt every stored token. Returns how many rows were rewritten."""

    if replacement.key_version <= current.key_version:
        raise RotationError(
            "the replacement key version must be greater than the current one "
            f"({replacement.key_version} <= {current.key_version})"
        )

    connections = (
        await session.execute(
            select(BankConnection).where(
                BankConnection.access_token_ciphertext.is_not(None)
            )
        )
    ).scalars().all()

    rotated = 0
    for connection in connections:
        if connection.access_token_key_version == replacement.key_version:
            continue  # already rotated, so a resumed run is safe
        if (
            connection.access_token_nonce is None
            or connection.access_token_key_version is None
        ):
            raise RotationError(
                f"connection {connection.id} has incomplete encrypted token fields"
            )

        try:
            plaintext = current.decrypt(
                EncryptedSecret(
                    ciphertext=connection.access_token_ciphertext or "",
                    nonce=connection.access_token_nonce,
                    key_version=connection.access_token_key_version,
                ),
                context=connection.id,
            )
        except ValueError as error:
            raise RotationError(
                f"connection {connection.id} could not be decrypted with the "
                "current key; rotation aborted and nothing was changed"
            ) from error

        encrypted = replacement.encrypt(plaintext, context=connection.id)
        connection.access_token_ciphertext = encrypted.ciphertext
        connection.access_token_nonce = encrypted.nonce
        connection.access_token_key_version = encrypted.key_version
        rotated += 1

    await session.flush()
    logger.info("token_key_rotated", extra={"rows": rotated})
    return rotated


__all__ = ["RotationError", "rotate_token_encryption_key"]
