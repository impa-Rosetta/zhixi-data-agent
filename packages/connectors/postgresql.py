import ipaddress
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg

from packages.connectors.base import (
    ConnectionCheck,
    ConnectionTarget,
    ConnectorCredentials,
    ConnectorError,
)
from packages.platform_core.models import DataSourceType, TlsMode
from packages.platform_core.network_policy import (
    NetworkPolicyError,
    NetworkPolicyRules,
    authorize_destination,
    resolve_host,
    verify_connected_address,
)

_SSL_MODES = {
    TlsMode.DISABLE: "disable",
    TlsMode.PREFER: "prefer",
    TlsMode.REQUIRE: "require",
    TlsMode.VERIFY_CA: "verify-ca",
    TlsMode.VERIFY_FULL: "verify-full",
}


@contextmanager
def _temporary_ca(certificate: str | None) -> Iterator[str | None]:
    if certificate is None:
        yield None
        return
    path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".pem", delete=False
        ) as handle:
            handle.write(certificate)
            path = handle.name
        yield path
    finally:
        if path is not None:
            Path(path).unlink(missing_ok=True)


def _readonly_query() -> str:
    return """
        SELECT
            current_setting('transaction_read_only') = 'on' AS session_read_only,
            NOT r.rolsuper
              AND NOT r.rolcreatedb
              AND NOT r.rolcreaterole
              AND NOT r.rolreplication
              AND NOT has_database_privilege(current_user, current_database(), 'CREATE')
              AND NOT EXISTS (
                SELECT 1
                FROM pg_namespace n
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND n.nspname NOT LIKE 'pg_toast%'
                  AND has_schema_privilege(current_user, n.oid, 'CREATE')
              )
              AND NOT EXISTS (
                SELECT 1
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND n.nspname NOT LIKE 'pg_toast%'
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND has_table_privilege(
                    current_user,
                    c.oid,
                    'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
                  )
              ) AS privileges_read_only
        FROM pg_roles r
        WHERE r.rolname = current_user
    """


class PostgreSQLConnector:
    source_type = DataSourceType.POSTGRESQL

    def test_connection(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: NetworkPolicyRules,
    ) -> ConnectionCheck:
        try:
            resolved = resolve_host(target.host)
            authorized = authorize_destination(target.host, target.port, resolved, network_rules)
        except NetworkPolicyError as exc:
            raise ConnectorError(exc.code) from exc

        last_error: Exception | None = None
        for address in authorized:
            try:
                return self._check_address(target, credentials, network_rules, authorized, address)
            except psycopg.Error as exc:
                last_error = exc
        raise self._map_connection_error(last_error)

    def _check_address(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: NetworkPolicyRules,
        authorized: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ) -> ConnectionCheck:
        with _temporary_ca(credentials.tls_ca_certificate) as ca_path:
            kwargs: dict[str, Any] = {
                "host": target.host,
                "hostaddr": str(address),
                "port": target.port,
                "dbname": target.database_name,
                "user": credentials.username,
                "password": credentials.password,
                "sslmode": _SSL_MODES[target.tls_mode],
                "connect_timeout": 5,
                "options": (
                    "-c default_transaction_read_only=on "
                    "-c statement_timeout=10000 -c lock_timeout=5000"
                ),
                "application_name": "zhixi-data-agent",
            }
            if ca_path is not None:
                kwargs["sslrootcert"] = ca_path
            with psycopg.connect(**kwargs) as connection:
                try:
                    connected = ipaddress.ip_address(connection.info.hostaddr)
                except ValueError as exc:
                    raise ConnectorError("connector.invalid_response") from exc
                try:
                    verify_connected_address(connected, authorized, network_rules)
                except NetworkPolicyError as exc:
                    raise ConnectorError(exc.code) from exc
                with connection.cursor() as cursor:
                    cursor.execute("SELECT version(), current_setting('server_version')")
                    version_row = cursor.fetchone()
                    cursor.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_ssl "
                        "WHERE pid = pg_backend_pid() AND ssl)"
                    )
                    tls_row = cursor.fetchone()
                    cursor.execute(_readonly_query())
                    readonly_row = cursor.fetchone()
                if version_row is None or tls_row is None or readonly_row is None:
                    raise ConnectorError("connector.invalid_response")
                tls_active = bool(tls_row[0])
                if (
                    target.tls_mode
                    in {
                        TlsMode.REQUIRE,
                        TlsMode.VERIFY_CA,
                        TlsMode.VERIFY_FULL,
                    }
                    and not tls_active
                ):
                    raise ConnectorError("connector.tls_required")
                read_only = bool(readonly_row[0]) and bool(readonly_row[1])
                if not read_only:
                    raise ConnectorError("connector.read_only_required")
                return ConnectionCheck(
                    database_product="postgresql",
                    database_version=str(version_row[1]),
                    connected_address=str(connected),
                    tls_active=tls_active,
                    read_only_verified=True,
                )

    @staticmethod
    def _map_connection_error(error: Exception | None) -> ConnectorError:
        if error is None:
            return ConnectorError("connector.connection_failed", retryable=True)
        text = str(error).lower()
        if "password authentication failed" in text or "authentication failed" in text:
            return ConnectorError("connector.authentication_failed")
        if "certificate" in text or "ssl" in text or "tls" in text:
            return ConnectorError("connector.tls_failed")
        if "permission denied" in text or "insufficient privilege" in text:
            return ConnectorError("connector.permission_denied")
        if "timeout" in text or "timed out" in text:
            return ConnectorError("connector.connection_timeout", retryable=True)
        return ConnectorError("connector.connection_failed", retryable=True)
