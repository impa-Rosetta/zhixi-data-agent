import base64
import binascii
import json
import os
import uuid
from dataclasses import dataclass, replace
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from packages.platform_core.settings import Settings

ALGORITHM = "AES-256-GCM"
FORMAT_VERSION = 1


class SecretConfigurationError(ValueError):
    pass


class SecretDecryptionError(ValueError):
    pass


@dataclass(frozen=True)
class EncryptedEnvelope:
    key_version: str
    wrapped_data_key: str
    key_nonce: str
    ciphertext: str
    payload_nonce: str
    algorithm: str = ALGORITHM
    format_version: int = FORMAT_VERSION


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SecretDecryptionError("Encrypted envelope contains invalid base64") from exc


def secret_aad(workspace_id: uuid.UUID, data_source_id: uuid.UUID) -> bytes:
    return (
        f"workspace:{workspace_id}|data-source:{data_source_id}|format:{FORMAT_VERSION}"
    ).encode()


class EnvelopeSecretProvider:
    def __init__(self, master_keys: dict[str, bytes], active_key_version: str) -> None:
        if active_key_version not in master_keys:
            raise SecretConfigurationError("Active master key version is unavailable")
        if any(len(key) != 32 for key in master_keys.values()):
            raise SecretConfigurationError("Every master key must contain exactly 32 bytes")
        self._master_keys = dict(master_keys)
        self._active_key_version = active_key_version

    @classmethod
    def from_settings(cls, settings: Settings) -> "EnvelopeSecretProvider":
        return cls(settings.data_source_master_keyring(), settings.data_source_active_key_version)

    def encrypt(self, credentials: dict[str, Any], aad: bytes) -> EncryptedEnvelope:
        payload = json.dumps(
            credentials,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        data_key = AESGCM.generate_key(bit_length=256)
        key_nonce = os.urandom(12)
        payload_nonce = os.urandom(12)
        master_key = self._master_keys[self._active_key_version]
        wrapped_data_key = AESGCM(master_key).encrypt(key_nonce, data_key, aad + b"|data-key")
        ciphertext = AESGCM(data_key).encrypt(payload_nonce, payload, aad + b"|credentials")
        return EncryptedEnvelope(
            key_version=self._active_key_version,
            wrapped_data_key=_encode(wrapped_data_key),
            key_nonce=_encode(key_nonce),
            ciphertext=_encode(ciphertext),
            payload_nonce=_encode(payload_nonce),
        )

    def decrypt(self, envelope: EncryptedEnvelope, aad: bytes) -> dict[str, Any]:
        if envelope.algorithm != ALGORITHM or envelope.format_version != FORMAT_VERSION:
            raise SecretDecryptionError("Encrypted envelope format is unsupported")
        master_key = self._master_keys.get(envelope.key_version)
        if master_key is None:
            raise SecretDecryptionError("Encrypted envelope key version is unavailable")
        try:
            data_key = AESGCM(master_key).decrypt(
                _decode(envelope.key_nonce),
                _decode(envelope.wrapped_data_key),
                aad + b"|data-key",
            )
            payload = AESGCM(data_key).decrypt(
                _decode(envelope.payload_nonce),
                _decode(envelope.ciphertext),
                aad + b"|credentials",
            )
            decoded = json.loads(payload)
        except (InvalidTag, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise SecretDecryptionError("Encrypted credentials could not be authenticated") from exc
        if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
            raise SecretDecryptionError("Encrypted credential payload is invalid")
        return decoded

    def rewrap(self, envelope: EncryptedEnvelope, aad: bytes) -> EncryptedEnvelope:
        if envelope.key_version == self._active_key_version:
            return envelope
        old_master_key = self._master_keys.get(envelope.key_version)
        if old_master_key is None:
            raise SecretDecryptionError("Previous master key version is unavailable")
        try:
            data_key = AESGCM(old_master_key).decrypt(
                _decode(envelope.key_nonce),
                _decode(envelope.wrapped_data_key),
                aad + b"|data-key",
            )
        except (InvalidTag, ValueError) as exc:
            raise SecretDecryptionError("Encrypted data key could not be authenticated") from exc
        nonce = os.urandom(12)
        wrapped = AESGCM(self._master_keys[self._active_key_version]).encrypt(
            nonce,
            data_key,
            aad + b"|data-key",
        )
        return replace(
            envelope,
            key_version=self._active_key_version,
            key_nonce=_encode(nonce),
            wrapped_data_key=_encode(wrapped),
        )
