import ipaddress
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg
import pymysql

from packages.connectors.base import ConnectionTarget, ConnectorCredentials, ConnectorError
from packages.connectors.mysql import _connect_address, _start_read_only
from packages.connectors.postgresql import _SSL_MODES, _temporary_ca
from packages.platform_core.models import DataSourceType
from packages.platform_core.network_policy import (
    NetworkPolicyError,
    NetworkPolicyRules,
    authorize_destination,
    resolve_host,
    verify_connected_address,
)


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    truncated: bool


def execute_read_only(
    source_type: DataSourceType,
    target: ConnectionTarget,
    credentials: ConnectorCredentials,
    network_rules: NetworkPolicyRules,
    sql: str,
    parameters: tuple[object, ...],
    *,
    row_limit: int,
    statement_timeout_seconds: int = 10,
) -> QueryResult:
    try:
        resolved = resolve_host(target.host)
        authorized = authorize_destination(target.host, target.port, resolved, network_rules)
    except NetworkPolicyError as exc:
        raise ConnectorError(exc.code) from exc
    last_error: Exception | None = None
    for address in authorized:
        try:
            if source_type is DataSourceType.POSTGRESQL:
                return _execute_postgres(
                    target,
                    credentials,
                    network_rules,
                    authorized,
                    address,
                    sql,
                    parameters,
                    row_limit,
                    statement_timeout_seconds,
                )
            return _execute_mysql(
                target,
                credentials,
                network_rules,
                authorized,
                address,
                sql,
                parameters,
                row_limit,
                statement_timeout_seconds,
            )
        except (psycopg.Error, pymysql.MySQLError, OSError) as exc:
            last_error = exc
    if (
        isinstance(last_error, (TimeoutError, psycopg.errors.QueryCanceled))
        or "timeout" in str(last_error).lower()
    ):
        raise ConnectorError("query.timeout", retryable=True) from last_error
    raise ConnectorError("query.execution_failed") from last_error


def _execute_postgres(
    target: ConnectionTarget,
    credentials: ConnectorCredentials,
    network_rules: NetworkPolicyRules,
    authorized: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    query: str,
    parameters: tuple[object, ...],
    row_limit: int,
    timeout: int,
) -> QueryResult:
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
                f"-c statement_timeout={timeout * 1000} -c lock_timeout=5000"
            ),
            "application_name": "zhixi-query-engine",
        }
        if ca_path is not None:
            kwargs["sslrootcert"] = ca_path
        with psycopg.connect(**kwargs) as connection:
            verify_connected_address(
                ipaddress.ip_address(connection.info.hostaddr), authorized, network_rules
            )
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(query, parameters)
                columns = tuple(item.name for item in (cursor.description or ()))
                rows = tuple(
                    tuple(_json_value(value) for value in row)
                    for row in cursor.fetchmany(row_limit + 1)
                )
            connection.rollback()
    return QueryResult(columns, rows[:row_limit], len(rows) > row_limit)


def _execute_mysql(
    target: ConnectionTarget,
    credentials: ConnectorCredentials,
    network_rules: NetworkPolicyRules,
    authorized: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    query: str,
    parameters: tuple[object, ...],
    row_limit: int,
    timeout: int,
) -> QueryResult:
    with _connect_address(target, credentials, network_rules, authorized, address) as connection:
        _start_read_only(connection, timeout)
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            columns = tuple(str(item[0]) for item in (cursor.description or ()))
            rows = tuple(
                tuple(_json_value(value) for value in row)
                for row in cursor.fetchmany(row_limit + 1)
            )
        connection.rollback()
    return QueryResult(columns, rows[:row_limit], len(rows) > row_limit)


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)
