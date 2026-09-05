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
from packages.connectors.metadata import (
    MetadataColumn,
    MetadataConstraint,
    MetadataDocument,
    MetadataIndex,
    MetadataRelation,
    MetadataScanOptions,
    MetadataSchema,
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

_SYSTEM_SCHEMAS = {"information_schema"}


def _portable_type(native_type: str, category: str) -> str:
    normalized = native_type.lower()
    if normalized == "uuid":
        return "uuid"
    if normalized in {"json", "jsonb"}:
        return "json"
    if category == "B":
        return "boolean"
    if category == "N":
        return "decimal" if "numeric" in normalized or "decimal" in normalized else "number"
    if category == "D":
        if "timestamp" in normalized:
            return "datetime"
        if normalized.startswith("date"):
            return "date"
        return "time"
    if category in {"S", "E"}:
        return "string"
    if category == "A" or normalized.endswith("[]"):
        return "array"
    if normalized in {"bytea", "bit", "bit varying"}:
        return "binary"
    return "other"


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

    def scan_metadata(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: NetworkPolicyRules,
        options: MetadataScanOptions,
    ) -> MetadataDocument:
        try:
            resolved = resolve_host(target.host)
            authorized = authorize_destination(target.host, target.port, resolved, network_rules)
        except NetworkPolicyError as exc:
            raise ConnectorError(exc.code) from exc
        last_error: Exception | None = None
        for address in authorized:
            try:
                return self._scan_address(
                    target, credentials, network_rules, authorized, address, options
                )
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

    def _scan_address(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: NetworkPolicyRules,
        authorized: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
        options: MetadataScanOptions,
    ) -> MetadataDocument:
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
                "application_name": "zhixi-data-agent-metadata",
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
                    cursor.execute("SELECT current_setting('server_version')")
                    version_row = cursor.fetchone()
                    cursor.execute(
                        """
                        SELECT n.nspname, obj_description(n.oid, 'pg_namespace')
                        FROM pg_namespace n
                        WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
                          AND has_schema_privilege(current_user, n.oid, 'USAGE')
                        ORDER BY n.nspname
                        """
                    )
                    schema_rows = cursor.fetchall()
                    available = {
                        str(row[0]): None if row[1] is None else str(row[1])
                        for row in schema_rows
                        if str(row[0]) not in _SYSTEM_SCHEMAS
                    }
                    selected = tuple(sorted(options.schemas or tuple(available)))
                    unknown = set(selected) - set(available)
                    if unknown:
                        raise ConnectorError("connector.schema_not_found")
                    relation_rows = self._relations(cursor, selected)
                    column_rows = self._columns(cursor, selected)
                    constraint_rows = self._constraints(cursor, selected)
                    index_rows = self._indexes(cursor, selected)
                if version_row is None:
                    raise ConnectorError("connector.invalid_response")
                count = (
                    len(selected)
                    + len(relation_rows)
                    + len(column_rows)
                    + len(constraint_rows)
                    + len(index_rows)
                )
                if count > options.max_objects:
                    raise ConnectorError("connector.scan_limit_exceeded")
                return self._document(
                    str(version_row[0]),
                    selected,
                    available,
                    relation_rows,
                    column_rows,
                    constraint_rows,
                    index_rows,
                )

    @staticmethod
    def _relations(cursor: Any, schemas: tuple[str, ...]) -> list[tuple[Any, ...]]:
        cursor.execute(
            """
            SELECT n.nspname, c.relname,
                   CASE c.relkind WHEN 'r' THEN 'table' WHEN 'p' THEN 'table'
                        WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized_view' END,
                   obj_description(c.oid, 'pg_class')
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p', 'v', 'm') AND n.nspname = ANY(%s)
              AND has_table_privilege(current_user, c.oid, 'SELECT')
            ORDER BY n.nspname, c.relname
            """,
            (list(schemas),),
        )
        return list(cursor.fetchall())

    @staticmethod
    def _columns(cursor: Any, schemas: tuple[str, ...]) -> list[tuple[Any, ...]]:
        cursor.execute(
            """
            SELECT n.nspname, c.relname, a.attname, a.attnum,
                   format_type(a.atttypid, a.atttypmod), t.typcategory,
                   NOT a.attnotnull, pg_get_expr(d.adbin, d.adrelid),
                   col_description(c.oid, a.attnum)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_type t ON t.oid = a.atttypid
            LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
            WHERE a.attnum > 0 AND NOT a.attisdropped
              AND c.relkind IN ('r', 'p', 'v', 'm') AND n.nspname = ANY(%s)
              AND has_table_privilege(current_user, c.oid, 'SELECT')
            ORDER BY n.nspname, c.relname, a.attnum
            """,
            (list(schemas),),
        )
        return list(cursor.fetchall())

    @staticmethod
    def _constraints(cursor: Any, schemas: tuple[str, ...]) -> list[tuple[Any, ...]]:
        cursor.execute(
            """
            SELECT n.nspname, c.relname, con.conname,
                   CASE con.contype WHEN 'p' THEN 'primary_key' WHEN 'f' THEN 'foreign_key'
                        WHEN 'u' THEN 'unique' WHEN 'c' THEN 'check' END,
                   ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(attnum, ord)
                         JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
                         ORDER BY k.ord),
                   rn.nspname, rc.relname,
                   ARRAY(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY k(attnum, ord)
                         JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum
                         ORDER BY k.ord)
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_class rc ON rc.oid = con.confrelid
            LEFT JOIN pg_namespace rn ON rn.oid = rc.relnamespace
            WHERE con.contype IN ('p', 'f', 'u', 'c') AND n.nspname = ANY(%s)
              AND has_table_privilege(current_user, c.oid, 'SELECT')
            ORDER BY n.nspname, c.relname, con.conname
            """,
            (list(schemas),),
        )
        return list(cursor.fetchall())

    @staticmethod
    def _indexes(cursor: Any, schemas: tuple[str, ...]) -> list[tuple[Any, ...]]:
        cursor.execute(
            """
            SELECT n.nspname, c.relname, ic.relname, i.indisunique, am.amname,
                   ARRAY(SELECT pg_get_indexdef(i.indexrelid, ord, true)
                         FROM generate_series(1, i.indnkeyatts) ord ORDER BY ord),
                   pg_get_expr(i.indpred, i.indrelid)
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_class ic ON ic.oid = i.indexrelid
            JOIN pg_am am ON am.oid = ic.relam
            WHERE n.nspname = ANY(%s)
              AND has_table_privilege(current_user, c.oid, 'SELECT')
            ORDER BY n.nspname, c.relname, ic.relname
            """,
            (list(schemas),),
        )
        return list(cursor.fetchall())

    @staticmethod
    def _document(
        version: str,
        selected: tuple[str, ...],
        comments: dict[str, str | None],
        relation_rows: list[tuple[Any, ...]],
        column_rows: list[tuple[Any, ...]],
        constraint_rows: list[tuple[Any, ...]],
        index_rows: list[tuple[Any, ...]],
    ) -> MetadataDocument:
        columns: dict[tuple[str, str], list[MetadataColumn]] = {}
        for row in column_rows:
            native_type = str(row[4])
            columns.setdefault((str(row[0]), str(row[1])), []).append(
                MetadataColumn(
                    name=str(row[2]),
                    ordinal_position=int(row[3]),
                    data_type=_portable_type(native_type, str(row[5])),
                    native_type=native_type,
                    nullable=bool(row[6]),
                    default_expression=None if row[7] is None else str(row[7]),
                    comment=None if row[8] is None else str(row[8]),
                )
            )
        constraints: dict[tuple[str, str], list[MetadataConstraint]] = {}
        for row in constraint_rows:
            constraints.setdefault((str(row[0]), str(row[1])), []).append(
                MetadataConstraint(
                    name=str(row[2]),
                    constraint_type=str(row[3]),
                    columns=tuple(str(item) for item in (row[4] or [])),
                    referenced_schema=None if row[5] is None else str(row[5]),
                    referenced_relation=None if row[6] is None else str(row[6]),
                    referenced_columns=tuple(str(item) for item in (row[7] or [])),
                )
            )
        indexes: dict[tuple[str, str], list[MetadataIndex]] = {}
        for row in index_rows:
            indexes.setdefault((str(row[0]), str(row[1])), []).append(
                MetadataIndex(
                    name=str(row[2]),
                    unique=bool(row[3]),
                    method=None if row[4] is None else str(row[4]),
                    columns=tuple(str(item) for item in (row[5] or [])),
                    predicate=None if row[6] is None else str(row[6]),
                )
            )
        relations = tuple(
            MetadataRelation(
                schema=str(row[0]),
                name=str(row[1]),
                relation_type=str(row[2]),
                comment=None if row[3] is None else str(row[3]),
                columns=tuple(columns.get((str(row[0]), str(row[1])), [])),
                constraints=tuple(constraints.get((str(row[0]), str(row[1])), [])),
                indexes=tuple(indexes.get((str(row[0]), str(row[1])), [])),
            )
            for row in relation_rows
        )
        return MetadataDocument(
            database_product="postgresql",
            database_version=version,
            schemas=tuple(MetadataSchema(name, comments.get(name)) for name in selected),
            relations=relations,
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
