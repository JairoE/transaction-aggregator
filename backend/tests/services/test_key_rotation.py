from __future__ import annotations

from base64 import urlsafe_b64encode
from os import urandom

import pytest
from sqlalchemy import select

from app.models import BankConnection
from app.services.crypto import EncryptedSecret, TokenCipher
from app.services.key_rotation import RotationError, rotate_token_encryption_key


def _new_key() -> str:
    return urlsafe_b64encode(urandom(32)).decode()


async def test_rotation_reencrypts_every_active_connection(
    db_session, connected_connection, token_cipher
) -> None:
    new_key = _new_key()
    new_cipher = TokenCipher.from_base64_key(new_key, key_version=2)

    before = (
        await db_session.execute(
            select(BankConnection).where(BankConnection.id == connected_connection.id)
        )
    ).scalars().one()
    original_ciphertext = before.access_token_ciphertext
    plaintext = token_cipher.decrypt(
        EncryptedSecret(
            ciphertext=before.access_token_ciphertext,
            nonce=before.access_token_nonce,
            key_version=before.access_token_key_version,
        ),
        context=before.id,
    )

    rotated = await rotate_token_encryption_key(db_session, token_cipher, new_cipher)
    await db_session.commit()

    assert rotated == 1
    await db_session.refresh(before)
    assert before.access_token_key_version == 2
    assert before.access_token_ciphertext != original_ciphertext
    assert (
        new_cipher.decrypt(
            EncryptedSecret(
                ciphertext=before.access_token_ciphertext,
                nonce=before.access_token_nonce,
                key_version=2,
            ),
            context=before.id,
        )
        == plaintext
    )


async def test_rotation_keeps_the_row_binding(
    db_session, connected_connection, token_cipher
) -> None:
    """Ciphertext must stay bound to its own row after rotation."""

    new_cipher = TokenCipher.from_base64_key(_new_key(), key_version=2)
    await rotate_token_encryption_key(db_session, token_cipher, new_cipher)
    await db_session.commit()

    row = (
        await db_session.execute(
            select(BankConnection).where(BankConnection.id == connected_connection.id)
        )
    ).scalars().one()

    with pytest.raises(ValueError):
        new_cipher.decrypt(
            EncryptedSecret(
                ciphertext=row.access_token_ciphertext,
                nonce=row.access_token_nonce,
                key_version=2,
            ),
            context="some-other-connection",
        )


async def test_rotation_is_idempotent(
    db_session, connected_connection, token_cipher
) -> None:
    new_cipher = TokenCipher.from_base64_key(_new_key(), key_version=2)

    first = await rotate_token_encryption_key(db_session, token_cipher, new_cipher)
    await db_session.commit()
    second = await rotate_token_encryption_key(db_session, token_cipher, new_cipher)
    await db_session.commit()

    assert (first, second) == (1, 0)


async def test_rotation_refuses_a_reused_version(
    db_session, connected_connection, token_cipher
) -> None:
    same_version = TokenCipher.from_base64_key(_new_key(), key_version=1)

    with pytest.raises(RotationError):
        await rotate_token_encryption_key(db_session, token_cipher, same_version)


async def test_a_row_that_cannot_be_decrypted_aborts_the_whole_rotation(
    db_session, connected_connection, token_cipher
) -> None:
    row = (
        await db_session.execute(
            select(BankConnection).where(BankConnection.id == connected_connection.id)
        )
    ).scalars().one()
    intact = row.access_token_ciphertext
    row.access_token_ciphertext = "AAAA" + (intact or "")[4:]
    await db_session.flush()

    new_cipher = TokenCipher.from_base64_key(_new_key(), key_version=2)

    with pytest.raises(RotationError):
        await rotate_token_encryption_key(db_session, token_cipher, new_cipher)

    await db_session.rollback()
    unchanged = (
        await db_session.execute(
            select(BankConnection).where(BankConnection.id == connected_connection.id)
        )
    ).scalars().one()
    assert unchanged.access_token_key_version == 1


async def test_tombstones_are_skipped(db_session, owner, token_cipher) -> None:
    from app.models import utcnow

    db_session.add(
        BankConnection(
            owner_id=owner.id,
            bank_slug="chase",
            institution_id="ins_3",
            institution_name="Chase",
            plaid_item_id="item-tombstone",
            plaid_environment="production",
            lifecycle_status="removed",
            removed_at=utcnow(),
        )
    )
    await db_session.flush()

    new_cipher = TokenCipher.from_base64_key(_new_key(), key_version=2)
    rotated = await rotate_token_encryption_key(db_session, token_cipher, new_cipher)

    assert rotated == 0


def test_cli_exposes_rotate_key() -> None:
    import argparse

    from app.cli import main

    with pytest.raises((SystemExit, argparse.ArgumentError)):
        main(["rotate-key"])  # --new-version is required
