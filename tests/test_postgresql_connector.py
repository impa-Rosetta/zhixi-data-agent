import ipaddress
from pathlib import Path
from typing import Any

import psycopg
import pytest

from packages.connectors.base import ConnectionTarget, ConnectorCredentials, ConnectorError
from packages.connectors.metadata import MetadataScanOptions
from packages.connectors.postgresql import PostgreSQLConnector
from packages.connectors.registry import ConnectorRegistry
from packages.platform_core.models import DataSourceType, TlsMode
from packages.platform_core.network_policy import NetworkPolicyRules


class FakeCursor:
    def __init__(
        self,
        *,
        tls: bool = True,
        session_read_only: bool = True,
        privileges_read_only: bool = True,
        missing_response: bool = False,
    ) -> None:
        self.tls = tls
        self.session_read_only = session_read_only
        self.privileges_read_only = privileges_read_only
        self.missing_response = missing_response
        self.query = ""

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str) -> None:
        self.query = query

    def fetchone(self) -> tuple[object, ...] | None:
        if self.missing_response:
            return None
        if "SELECT version()" in self.query:
            return ("PostgreSQL 16.4", "16.4")
        if "pg_stat_ssl" in self.query:
            return (self.tls,)
        return (self.session_read_only, self.privileges_read_only)


class FakeInfo:
    def __init__(self, hostaddr: str) -> None:
        self.hostaddr = hostaddr


class FakeConnection:
    def __init__(self, cursor: FakeCursor, hostaddr: str = "8.8.8.8") -> None:
        self._cursor = cursor
        self.info = FakeInfo(hostaddr)

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self._cursor


@pytest.fixture
def rules() -> NetworkPolicyRules:
    return NetworkPolicyRules.from_strings(allowed_private_cidrs=[], allowed_ports=[5432])


def target(tls_mode: TlsMode = TlsMode.REQUIRE) -> ConnectionTarget:
    return ConnectionTarget("db.example.com", 5432, "factory", tls_mode)


def patch_connection(
    monkeypatch: pytest.MonkeyPatch,
    cursor: FakeCursor,
    *,
    hostaddr: str = "8.8.8.8",
) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "packages.connectors.postgresql.resolve_host",
        lambda _: (ipaddress.ip_address("8.8.8.8"),),
    )

    def connect(**kwargs: Any) -> FakeConnection:
        captured.update(kwargs)
        if root := kwargs.get("sslrootcert"):
            assert Path(root).exists()
        return FakeConnection(cursor, hostaddr)

    monkeypatch.setattr("packages.connectors.postgresql.psycopg.connect", connect)
    return captured


def test_postgresql_connection_verifies_tls_readonly_and_pins_address(
    monkeypatch: pytest.MonkeyPatch, rules: NetworkPolicyRules
) -> None:
    captured = patch_connection(monkeypatch, FakeCursor())
    result = PostgreSQLConnector().test_connection(
        target(),
        ConnectorCredentials("reader", "secret", "TEST CA"),
        rules,
    )
    assert result.database_product == "postgresql"
    assert result.database_version == "16.4"
    assert result.tls_active is True
    assert result.read_only_verified is True
    assert captured["hostaddr"] == "8.8.8.8"
    assert captured["sslmode"] == "require"
    assert "default_transaction_read_only=on" in captured["options"]
    assert not Path(captured["sslrootcert"]).exists()


@pytest.mark.parametrize(
    ("cursor", "mode", "code"),
    [
        (FakeCursor(privileges_read_only=False), TlsMode.REQUIRE, "connector.read_only_required"),
        (FakeCursor(tls=False), TlsMode.REQUIRE, "connector.tls_required"),
        (FakeCursor(missing_response=True), TlsMode.DISABLE, "connector.invalid_response"),
    ],
)
def test_postgresql_connection_rejects_unsafe_responses(
    monkeypatch: pytest.MonkeyPatch,
    rules: NetworkPolicyRules,
    cursor: FakeCursor,
    mode: TlsMode,
    code: str,
) -> None:
    patch_connection(monkeypatch, cursor)
    with pytest.raises(ConnectorError) as raised:
        PostgreSQLConnector().test_connection(
            target(mode), ConnectorCredentials("reader", "secret"), rules
        )
    assert raised.value.code == code


def test_postgresql_connection_rejects_rebound_address(
    monkeypatch: pytest.MonkeyPatch, rules: NetworkPolicyRules
) -> None:
    patch_connection(monkeypatch, FakeCursor(), hostaddr="8.8.4.4")
    with pytest.raises(ConnectorError) as raised:
        PostgreSQLConnector().test_connection(
            target(), ConnectorCredentials("reader", "secret"), rules
        )
    assert raised.value.code == "network_policy.dns_rebinding"


@pytest.mark.parametrize(
    ("message", "code", "retryable"),
    [
        ("password authentication failed", "connector.authentication_failed", False),
        ("SSL certificate verify failed", "connector.tls_failed", False),
        ("permission denied for relation", "connector.permission_denied", False),
        ("connection timed out", "connector.connection_timeout", True),
        ("connection refused", "connector.connection_failed", True),
    ],
)
def test_postgresql_errors_are_safely_classified(
    monkeypatch: pytest.MonkeyPatch,
    rules: NetworkPolicyRules,
    message: str,
    code: str,
    retryable: bool,
) -> None:
    monkeypatch.setattr(
        "packages.connectors.postgresql.resolve_host",
        lambda _: (ipaddress.ip_address("8.8.8.8"),),
    )

    def fail(**_: Any) -> FakeConnection:
        raise psycopg.OperationalError(message)

    monkeypatch.setattr("packages.connectors.postgresql.psycopg.connect", fail)
    with pytest.raises(ConnectorError) as raised:
        PostgreSQLConnector().test_connection(
            target(), ConnectorCredentials("reader", "secret"), rules
        )
    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert message not in str(raised.value)


def test_registry_rejects_unavailable_connector() -> None:
    with pytest.raises(ConnectorError) as raised:
        ConnectorRegistry().get(DataSourceType.MYSQL)
    assert raised.value.code == "connector.unsupported"


class MetadataCursor:
    def __init__(self) -> None:
        self.query = ""
        self.params: object = None

    def __enter__(self) -> "MetadataCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: object = None) -> None:
        self.query = query
        self.params = params

    def fetchone(self) -> tuple[str]:
        return ("16.4",)

    def fetchall(self) -> list[tuple[object, ...]]:
        if "FROM pg_namespace" in self.query:
            return [("analytics", "Reporting schema"), ("public", None)]
        if "CASE c.relkind" in self.query:
            return [("public", "orders", "table", "Production orders")]
        if "FROM pg_attribute" in self.query:
            return [
                ("public", "orders", "id", 1, "bigint", "N", False, None, "Identity"),
                ("public", "orders", "payload", 2, "jsonb", "U", True, None, None),
            ]
        if "FROM pg_constraint" in self.query:
            return [("public", "orders", "orders_pkey", "primary_key", ["id"], None, None, [])]
        if "FROM pg_index" in self.query:
            return [("public", "orders", "orders_pkey", True, "btree", ["id"], None)]
        raise AssertionError(f"Unexpected query: {self.query}")


def test_postgresql_metadata_scan_normalizes_catalog(
    monkeypatch: pytest.MonkeyPatch, rules: NetworkPolicyRules
) -> None:
    cursor = MetadataCursor()
    patch_connection(monkeypatch, cursor)  # type: ignore[arg-type]
    document = PostgreSQLConnector().scan_metadata(
        target(TlsMode.DISABLE),
        ConnectorCredentials("reader", "secret"),
        rules,
        MetadataScanOptions(schemas=("public",)),
    )
    assert [item.name for item in document.schemas] == ["public"]
    relation = document.relations[0]
    assert relation.relation_type == "table"
    assert [(item.name, item.data_type) for item in relation.columns] == [
        ("id", "number"),
        ("payload", "json"),
    ]
    assert relation.constraints[0].constraint_type == "primary_key"
    assert relation.indexes[0].method == "btree"
    assert cursor.params == (["public"],)


def test_postgresql_metadata_scan_rejects_unknown_schema_and_object_overflow(
    monkeypatch: pytest.MonkeyPatch, rules: NetworkPolicyRules
) -> None:
    cursor = MetadataCursor()
    patch_connection(monkeypatch, cursor)  # type: ignore[arg-type]
    connector = PostgreSQLConnector()
    with pytest.raises(ConnectorError) as unknown:
        connector.scan_metadata(
            target(TlsMode.DISABLE),
            ConnectorCredentials("reader", "secret"),
            rules,
            MetadataScanOptions(schemas=("missing",)),
        )
    assert unknown.value.code == "connector.schema_not_found"

    with pytest.raises(ConnectorError) as overflow:
        connector.scan_metadata(
            target(TlsMode.DISABLE),
            ConnectorCredentials("reader", "secret"),
            rules,
            MetadataScanOptions(schemas=("public",), max_objects=2),
        )
    assert overflow.value.code == "connector.scan_limit_exceeded"
