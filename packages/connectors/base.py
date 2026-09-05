from dataclasses import dataclass
from typing import Protocol

from packages.connectors.metadata import MetadataDocument, MetadataScanOptions
from packages.connectors.profiling import ProfileDocument, ProfileScanOptions
from packages.platform_core.models import DataSourceType, TlsMode
from packages.platform_core.network_policy import NetworkPolicyRules


@dataclass(frozen=True)
class ConnectionTarget:
    host: str
    port: int
    database_name: str
    tls_mode: TlsMode


@dataclass(frozen=True)
class ConnectorCredentials:
    username: str
    password: str
    tls_ca_certificate: str | None = None


@dataclass(frozen=True)
class ConnectionCheck:
    database_product: str
    database_version: str
    connected_address: str
    tls_active: bool
    read_only_verified: bool


class ConnectorError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class DatabaseConnector(Protocol):
    source_type: DataSourceType

    def test_connection(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: NetworkPolicyRules,
    ) -> ConnectionCheck: ...

    def scan_metadata(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: NetworkPolicyRules,
        options: MetadataScanOptions,
    ) -> MetadataDocument: ...

    def profile_data(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: NetworkPolicyRules,
        options: ProfileScanOptions,
    ) -> ProfileDocument: ...
