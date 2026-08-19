from base64 import urlsafe_b64encode
from os import urandom

import pytest

from app.services.crypto import EncryptedSecret, TokenCipher


def _key() -> str:
    return urlsafe_b64encode(urandom(32)).decode()


def test_access_token_round_trip_does_not_store_plaintext() -> None:
    key = _key()
    cipher = TokenCipher.from_base64_key(key, key_version=1)

    encrypted = cipher.encrypt("access-production-secret")

    assert "access-production-secret" not in encrypted.ciphertext
    assert encrypted.key_version == 1
    assert cipher.decrypt(encrypted) == "access-production-secret"


def test_each_encryption_uses_a_fresh_nonce() -> None:
    cipher = TokenCipher.from_base64_key(_key(), key_version=1)

    first = cipher.encrypt("access-sandbox-token")
    second = cipher.encrypt("access-sandbox-token")

    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert cipher.decrypt(first) == cipher.decrypt(second) == "access-sandbox-token"


def test_key_version_is_authenticated_associated_data() -> None:
    key = _key()
    cipher = TokenCipher.from_base64_key(key, key_version=1)
    encrypted = cipher.encrypt("access-sandbox-token")

    rotated = TokenCipher.from_base64_key(key, key_version=2)

    with pytest.raises(ValueError):
        rotated.decrypt(
            EncryptedSecret(
                ciphertext=encrypted.ciphertext,
                nonce=encrypted.nonce,
                key_version=2,
            )
        )


def test_tampered_ciphertext_is_rejected() -> None:
    cipher = TokenCipher.from_base64_key(_key(), key_version=1)
    encrypted = cipher.encrypt("access-sandbox-token")
    tampered = "A" if encrypted.ciphertext[0] != "A" else "B"

    with pytest.raises(ValueError):
        cipher.decrypt(
            EncryptedSecret(
                ciphertext=tampered + encrypted.ciphertext[1:],
                nonce=encrypted.nonce,
                key_version=1,
            )
        )


def test_key_must_decode_to_exactly_32_bytes() -> None:
    short_key = urlsafe_b64encode(urandom(16)).decode()

    with pytest.raises(ValueError):
        TokenCipher.from_base64_key(short_key, key_version=1)


def test_decrypt_rejects_unknown_key_version() -> None:
    cipher = TokenCipher.from_base64_key(_key(), key_version=1)
    encrypted = cipher.encrypt("access-sandbox-token")

    with pytest.raises(ValueError):
        cipher.decrypt(
            EncryptedSecret(
                ciphertext=encrypted.ciphertext,
                nonce=encrypted.nonce,
                key_version=9,
            )
        )
