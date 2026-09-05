from sqlalchemy.orm import Session

from packages.connectors.base import ConnectorCredentials
from packages.platform_core.models import DataSource, DataSourceSecret, NetworkPolicy
from packages.platform_core.network_policy import NetworkPolicyRules
from packages.platform_core.secrets import (
    EncryptedEnvelope,
    EnvelopeSecretProvider,
    SecretDecryptionError,
    secret_aad,
)
from packages.platform_core.settings import Settings


def load_runtime_credentials(
    db: Session, source: DataSource, settings: Settings
) -> tuple[ConnectorCredentials, NetworkPolicyRules]:
    """Decrypt connector credentials only inside a worker execution boundary."""
    secret = db.get(DataSourceSecret, source.id)
    policy = db.get(NetworkPolicy, source.network_policy_id) if source.network_policy_id else None
    if secret is None or secret.destroyed_at is not None or policy is None:
        raise SecretDecryptionError("Data source runtime configuration is unavailable")
    envelope = EncryptedEnvelope(
        key_version=secret.key_version,
        wrapped_data_key=secret.wrapped_data_key,
        key_nonce=secret.key_nonce,
        ciphertext=secret.ciphertext,
        payload_nonce=secret.payload_nonce,
        algorithm=secret.algorithm,
        format_version=secret.format_version,
    )
    payload = EnvelopeSecretProvider.from_settings(settings).decrypt(
        envelope, secret_aad(source.workspace_id, source.id)
    )
    username = payload.get("username")
    password = payload.get("password")
    ca = payload.get("tls_ca_certificate")
    if not isinstance(username, str) or not isinstance(password, str):
        raise SecretDecryptionError("Encrypted credential payload is invalid")
    if ca is not None and not isinstance(ca, str):
        raise SecretDecryptionError("Encrypted credential payload is invalid")
    return (
        ConnectorCredentials(username, password, ca),
        NetworkPolicyRules.from_strings(
            allowed_private_cidrs=policy.allowed_private_cidrs,
            allowed_ports=policy.allowed_ports,
        ),
    )
