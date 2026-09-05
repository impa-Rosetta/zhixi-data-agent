import base64
import uuid
from dataclasses import replace

import pytest

from packages.platform_core.secrets import (
    EncryptedEnvelope,
    EnvelopeSecretProvider,
    SecretDecryptionError,
    secret_aad,
)


def provider(*, active: str = "v1") -> EnvelopeSecretProvider:
    return EnvelopeSecretProvider({"v1": b"a" * 32, "v2": b"b" * 32}, active)


def context() -> tuple[uuid.UUID, uuid.UUID, bytes]:
    workspace_id = uuid.uuid4()
    data_source_id = uuid.uuid4()
    return workspace_id, data_source_id, secret_aad(workspace_id, data_source_id)


def tamper(value: str) -> str:
    decoded = bytearray(base64.b64decode(value))
    decoded[-1] ^= 1
    return base64.b64encode(decoded).decode("ascii")


def test_credentials_round_trip_without_plaintext_in_envelope() -> None:
    _, _, aad = context()
    credentials = {"username": "reader", "password": "sensitive-value", "ssl": True}

    envelope = provider().encrypt(credentials, aad)

    assert provider().decrypt(envelope, aad) == credentials
    assert "sensitive-value" not in repr(envelope)


@pytest.mark.parametrize("field", ["wrapped_data_key", "ciphertext"])
def test_tampered_envelope_is_rejected(field: str) -> None:
    _, _, aad = context()
    envelope = provider().encrypt({"password": "secret"}, aad)
    corrupted = replace(envelope, **{field: tamper(getattr(envelope, field))})

    with pytest.raises(SecretDecryptionError):
        provider().decrypt(corrupted, aad)


def test_envelope_cannot_move_between_data_sources() -> None:
    workspace_id, _, aad = context()
    envelope = provider().encrypt({"password": "secret"}, aad)

    with pytest.raises(SecretDecryptionError):
        provider().decrypt(envelope, secret_aad(workspace_id, uuid.uuid4()))


def test_data_key_can_be_rewrapped_without_reencrypting_credentials() -> None:
    _, _, aad = context()
    original = provider(active="v1").encrypt({"password": "secret"}, aad)

    rewrapped = provider(active="v2").rewrap(original, aad)

    assert rewrapped.key_version == "v2"
    assert rewrapped.ciphertext == original.ciphertext
    assert rewrapped.payload_nonce == original.payload_nonce
    assert provider(active="v2").decrypt(rewrapped, aad) == {"password": "secret"}


def test_unknown_key_version_is_rejected() -> None:
    _, _, aad = context()
    envelope = EncryptedEnvelope(
        key_version="missing",
        wrapped_data_key="AA==",
        key_nonce="AA==",
        ciphertext="AA==",
        payload_nonce="AA==",
    )

    with pytest.raises(SecretDecryptionError):
        provider().decrypt(envelope, aad)
