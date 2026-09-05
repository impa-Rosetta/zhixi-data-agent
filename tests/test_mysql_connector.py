import ipaddress
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pymysql
import pytest

from packages.connectors.base import ConnectionTarget, ConnectorCredentials, ConnectorError
from packages.connectors.metadata import MetadataScanOptions
from packages.connectors.mysql import (
    MySQLConnector,
    _connect_address,
    _grantee,
    _portable_type,
    _temporary_ca,
    _tls_options,
)
from packages.connectors.registry import ConnectorRegistry
from packages.platform_core.models import DataSourceType, TlsMode
from packages.platform_core.network_policy import NetworkPolicyRules


class FakeCursor:
    def __init__(
        self,
        *,
        tls_cipher: str = "TLS_AES_256_GCM_SHA384",
        unsafe_privilege: str | None = None,
        enabled_role: bool = False,
    ) -> None:
        self.query = ""
        self.params: object = None
        self.tls_cipher = tls_cipher
        self.unsafe_privilege = unsafe_privilege
        self.enabled_role = enabled_role

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: object = None) -> None:
        self.query = query
        self.params = params

    def fetchone(self) -> tuple[object, ...] | None:
        if "VERSION()" in self.query:
            return ("8.4.6", "reader@%")
        if "Ssl_cipher" in self.query:
            return ("Ssl_cipher", self.tls_cipher)
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        if "ENABLED_ROLES" in self.query:
            return [("writer_role", "%")] if self.enabled_role else []
        if "USER_PRIVILEGES" in self.query:
            values = [("SELECT",), ("SHOW VIEW",)]
            if self.unsafe_privilege:
                values.append((self.unsafe_privilege,))
            return values
        if "FROM information_schema.SCHEMATA" in self.query:
            return [("factory_demo", None)]
        if "FROM information_schema.TABLES" in self.query:
            return [
                ("factory_demo", "order_summary", "view", ""),
                ("factory_demo", "production_orders", "table", "Production orders"),
            ]
        if "FROM information_schema.COLUMNS" in self.query:
            return [
                (
                    "factory_demo",
                    "production_orders",
                    "id",
                    1,
                    "bigint unsigned",
                    "bigint",
                    "NO",
                    None,
                    "Identity",
                ),
                (
                    "factory_demo",
                    "production_orders",
                    "payload",
                    2,
                    "json",
                    "json",
                    "YES",
                    None,
                    "",
                ),
            ]
        if "FROM information_schema.TABLE_CONSTRAINTS" in self.query:
            return [
                (
                    "factory_demo",
                    "production_orders",
                    "PRIMARY",
                    "primary_key",
                    "id",
                    1,
                    None,
                    None,
                    None,
                )
            ]
        if "FROM information_schema.STATISTICS" in self.query:
            return [
                (
                    "factory_demo",
                    "production_orders",
                    "PRIMARY",
                    False,
                    "BTREE",
                    1,
                    "id",
                    None,
                )
            ]
        raise AssertionError(f"Unexpected query: {self.query}")


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


@pytest.fixture
def rules() -> NetworkPolicyRules:
    return NetworkPolicyRules.from_strings(allowed_private_cidrs=[], allowed_ports=[3306])


def target(tls_mode: TlsMode = TlsMode.REQUIRE) -> ConnectionTarget:
    return ConnectionTarget("mysql.example.com", 3306, "factory_demo", tls_mode)


def patch_connection(monkeypatch: pytest.MonkeyPatch, cursor: FakeCursor) -> dict[str, object]:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "packages.connectors.mysql.resolve_host",
        lambda _: (ipaddress.ip_address("8.8.8.8"),),
    )

    @contextmanager
    def connect(*args: object, **kwargs: object) -> Any:
        captured["args"] = args
        captured["kwargs"] = kwargs
        yield FakeConnection(cursor)

    monkeypatch.setattr("packages.connectors.mysql._connect_address", connect)
    return captured


def test_mysql_connection_verifies_tls_readonly_and_pins_address(
    monkeypatch: pytest.MonkeyPatch, rules: NetworkPolicyRules
) -> None:
    captured = patch_connection(monkeypatch, FakeCursor())
    result = MySQLConnector().test_connection(
        target(), ConnectorCredentials("reader", "secret"), rules
    )
    assert result.database_product == "mysql"
    assert result.database_version == "8.4.6"
    assert result.connected_address == "8.8.8.8"
    assert result.tls_active is True
    assert result.read_only_verified is True
    assert captured["args"][-1] == ipaddress.ip_address("8.8.8.8")


@pytest.mark.parametrize(
    ("cursor", "mode", "code"),
    [
        (FakeCursor(unsafe_privilege="INSERT"), TlsMode.REQUIRE, "connector.read_only_required"),
        (FakeCursor(enabled_role=True), TlsMode.REQUIRE, "connector.read_only_required"),
        (FakeCursor(tls_cipher=""), TlsMode.REQUIRE, "connector.tls_required"),
    ],
)
def test_mysql_connection_rejects_unsafe_responses(
    monkeypatch: pytest.MonkeyPatch,
    rules: NetworkPolicyRules,
    cursor: FakeCursor,
    mode: TlsMode,
    code: str,
) -> None:
    patch_connection(monkeypatch, cursor)
    with pytest.raises(ConnectorError) as raised:
        MySQLConnector().test_connection(
            target(mode), ConnectorCredentials("reader", "secret"), rules
        )
    assert raised.value.code == code


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (
            pymysql.err.OperationalError(1045, "Access denied"),
            "connector.authentication_failed",
            False,
        ),
        (pymysql.err.OperationalError(1044, "Access denied"), "connector.permission_denied", False),
        (pymysql.err.OperationalError(2026, "SSL error"), "connector.tls_failed", False),
        (pymysql.err.OperationalError(2003, "timed out"), "connector.connection_timeout", True),
        (pymysql.err.OperationalError(2006, "gone away"), "connector.connection_failed", True),
    ],
)
def test_mysql_errors_are_safely_classified(
    error: pymysql.MySQLError, code: str, retryable: bool
) -> None:
    mapped = MySQLConnector._map_connection_error(error)
    assert mapped.code == code
    assert mapped.retryable is retryable
    assert str(error) not in str(mapped)


def test_mysql_metadata_scan_normalizes_catalog(
    monkeypatch: pytest.MonkeyPatch, rules: NetworkPolicyRules
) -> None:
    cursor = FakeCursor(tls_cipher="")
    patch_connection(monkeypatch, cursor)
    document = MySQLConnector().scan_metadata(
        target(TlsMode.DISABLE),
        ConnectorCredentials("reader", "secret"),
        rules,
        MetadataScanOptions(),
    )
    assert document.database_product == "mysql"
    assert [item.name for item in document.schemas] == ["factory_demo"]
    assert [item.relation_type for item in document.relations] == ["view", "table"]
    relation = document.relations[1]
    assert [(item.name, item.data_type) for item in relation.columns] == [
        ("id", "number"),
        ("payload", "json"),
    ]
    assert relation.constraints[0].constraint_type == "primary_key"
    assert relation.indexes[0].method == "btree"


def test_mysql_metadata_scan_rejects_cross_database_scope_and_object_overflow(
    monkeypatch: pytest.MonkeyPatch, rules: NetworkPolicyRules
) -> None:
    patch_connection(monkeypatch, FakeCursor(tls_cipher=""))
    connector = MySQLConnector()
    with pytest.raises(ConnectorError) as unknown:
        connector.scan_metadata(
            target(TlsMode.DISABLE),
            ConnectorCredentials("reader", "secret"),
            rules,
            MetadataScanOptions(schemas=("another_database",)),
        )
    assert unknown.value.code == "connector.schema_not_found"

    with pytest.raises(ConnectorError) as overflow:
        connector.scan_metadata(
            target(TlsMode.DISABLE),
            ConnectorCredentials("reader", "secret"),
            rules,
            MetadataScanOptions(max_objects=2),
        )
    assert overflow.value.code == "connector.scan_limit_exceeded"


@pytest.mark.parametrize(
    ("native_type", "data_type", "portable"),
    [
        ("tinyint(1)", "tinyint", "boolean"),
        ("decimal(12,2)", "decimal", "decimal"),
        ("timestamp(6)", "timestamp", "datetime"),
        ("longblob", "longblob", "binary"),
        ("enum('new','done')", "enum", "string"),
    ],
)
def test_mysql_type_mapping(native_type: str, data_type: str, portable: str) -> None:
    assert _portable_type(native_type, data_type) == portable


def test_registry_includes_mysql_connector() -> None:
    assert ConnectorRegistry().get(DataSourceType.MYSQL).source_type is DataSourceType.MYSQL


def test_mysql_tls_modes_are_explicit() -> None:
    disabled_context, disabled = _tls_options(TlsMode.DISABLE, None)
    assert disabled_context is None and disabled is True
    required_context, required_disabled = _tls_options(TlsMode.REQUIRE, None)
    assert required_context is not None
    assert required_context.check_hostname is False
    assert required_disabled is None
    with pytest.raises(ConnectorError) as missing_ca:
        _tls_options(TlsMode.VERIFY_CA, None)
    assert missing_ca.value.code == "connector.configuration_invalid"


def test_mysql_verified_tls_modes_use_ca_and_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeContext:
        check_hostname = True

    contexts: list[FakeContext] = []

    def create_context(*, cafile: str) -> FakeContext:
        assert cafile == "ca.pem"
        context = FakeContext()
        contexts.append(context)
        return context

    monkeypatch.setattr("packages.connectors.mysql.ssl.create_default_context", create_context)
    verify_ca, _ = _tls_options(TlsMode.VERIFY_CA, "ca.pem")
    verify_full, _ = _tls_options(TlsMode.VERIFY_FULL, "ca.pem")
    assert verify_ca is contexts[0] and contexts[0].check_hostname is False
    assert verify_full is contexts[1] and contexts[1].check_hostname is True


def test_mysql_temporary_ca_is_removed() -> None:
    with _temporary_ca("TEST CA") as path:
        assert path is not None
        certificate = Path(path)
        assert certificate.read_text(encoding="utf-8") == "TEST CA"
    assert not certificate.exists()


def test_mysql_connects_pre_authorized_socket_and_closes_it(
    monkeypatch: pytest.MonkeyPatch, rules: NetworkPolicyRules
) -> None:
    address = ipaddress.ip_address("8.8.8.8")

    class FakeSocket:
        closed = False

        def getpeername(self) -> tuple[str, int]:
            return str(address), 3306

        def close(self) -> None:
            self.closed = True

    class DriverConnection:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.open = False
            self.socket: FakeSocket | None = None

        def connect(self, sock: FakeSocket) -> None:
            self.socket = sock
            self.open = True

        def close(self) -> None:
            self.open = False

    raw = FakeSocket()
    created: list[DriverConnection] = []
    monkeypatch.setattr(
        "packages.connectors.mysql.socket.create_connection",
        lambda *_args, **_kwargs: raw,
    )

    def connection_factory(**kwargs: object) -> DriverConnection:
        connection = DriverConnection(**kwargs)
        created.append(connection)
        return connection

    monkeypatch.setattr(
        "packages.connectors.mysql.pymysql.connections.Connection", connection_factory
    )
    with _connect_address(
        target(TlsMode.DISABLE),
        ConnectorCredentials("reader", "secret"),
        rules,
        (address,),
        address,
    ) as connection:
        connected = cast(Any, connection)
        assert connected is created[0]
        assert connected.socket is raw
        assert connected.kwargs["host"] == "mysql.example.com"
        assert connected.kwargs["ssl_disabled"] is True
    assert created[0].open is False


def test_mysql_rejects_network_policy_and_invalid_current_user(
    monkeypatch: pytest.MonkeyPatch, rules: NetworkPolicyRules
) -> None:
    monkeypatch.setattr(
        "packages.connectors.mysql.resolve_host",
        lambda _: (ipaddress.ip_address("127.0.0.1"),),
    )
    with pytest.raises(ConnectorError) as blocked:
        MySQLConnector().test_connection(
            target(TlsMode.DISABLE), ConnectorCredentials("reader", "secret"), rules
        )
    assert blocked.value.code == "network_policy.address_denied"
    with pytest.raises(ConnectorError) as invalid:
        _grantee("missing-host")
    assert invalid.value.code == "connector.invalid_response"
