import ipaddress
import socket
import ssl
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pymysql

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
from packages.connectors.profiling import (
    ProfileDocument,
    ProfileScanOptions,
    SampledColumn,
    SampledRelation,
)
from packages.platform_core.models import DataSourceType, TlsMode
from packages.platform_core.network_policy import (
    NetworkPolicyError,
    NetworkPolicyRules,
    authorize_destination,
    resolve_host,
    verify_connected_address,
)
from packages.platform_core.profiling import build_profile_document, is_sampleable_type

_SYSTEM_SCHEMAS = {"information_schema", "mysql", "performance_schema", "sys"}
_READ_ONLY_PRIVILEGES = {"SELECT", "SHOW VIEW", "USAGE"}


def _portable_type(native_type: str, data_type: str) -> str:
    native = native_type.lower()
    normalized = data_type.lower()
    if normalized == "tinyint" and native.startswith("tinyint(1)"):
        return "boolean"
    if normalized in {"decimal", "numeric"}:
        return "decimal"
    if normalized in {
        "bigint",
        "bit",
        "double",
        "float",
        "int",
        "integer",
        "mediumint",
        "real",
        "smallint",
        "tinyint",
    }:
        return "number"
    if normalized in {"datetime", "timestamp"}:
        return "datetime"
    if normalized == "date":
        return "date"
    if normalized in {"time", "year"}:
        return "time"
    if normalized == "json":
        return "json"
    if normalized in {
        "binary",
        "blob",
        "longblob",
        "mediumblob",
        "tinyblob",
        "varbinary",
    }:
        return "binary"
    if normalized in {
        "char",
        "enum",
        "longtext",
        "mediumtext",
        "set",
        "text",
        "tinytext",
        "varchar",
    }:
        return "string"
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


def _tls_options(mode: TlsMode, ca_path: str | None) -> tuple[ssl.SSLContext | None, bool | None]:
    if mode is TlsMode.DISABLE:
        return None, True
    if mode is TlsMode.PREFER:
        return None, None
    if mode is TlsMode.REQUIRE:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context, None
    if ca_path is None:
        raise ConnectorError("connector.configuration_invalid")
    context = ssl.create_default_context(cafile=ca_path)
    context.check_hostname = mode is TlsMode.VERIFY_FULL
    return context, None


@contextmanager
def _connect_address(
    target: ConnectionTarget,
    credentials: ConnectorCredentials,
    network_rules: NetworkPolicyRules,
    authorized: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> Iterator[pymysql.connections.Connection]:
    raw_socket: socket.socket | None = None
    connection: pymysql.connections.Connection | None = None
    with _temporary_ca(credentials.tls_ca_certificate) as ca_path:
        try:
            raw_socket = socket.create_connection((str(address), target.port), timeout=5)
            peer = ipaddress.ip_address(raw_socket.getpeername()[0])
            verify_connected_address(peer, authorized, network_rules)
            tls_context, ssl_disabled = _tls_options(target.tls_mode, ca_path)
            connection = pymysql.connections.Connection(
                host=target.host,
                port=target.port,
                user=credentials.username,
                password=credentials.password,
                database=target.database_name,
                charset="utf8mb4",
                autocommit=False,
                local_infile=False,
                connect_timeout=5,
                read_timeout=10,
                write_timeout=10,
                program_name="zhixi-data-agent",
                defer_connect=True,
                ssl=tls_context,
                ssl_disabled=ssl_disabled,
            )
            connection.connect(raw_socket)
            yield connection
        except NetworkPolicyError as exc:
            raise ConnectorError(exc.code) from exc
        finally:
            if connection is not None and connection.open:
                connection.close()
            elif raw_socket is not None:
                raw_socket.close()


def _start_read_only(
    connection: pymysql.connections.Connection, statement_timeout_seconds: int = 10
) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET SESSION TRANSACTION READ ONLY")
        cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {int(statement_timeout_seconds) * 1000}")
        cursor.execute("SET SESSION lock_wait_timeout = 5")
        cursor.execute("START TRANSACTION READ ONLY")


def _grantee(current_user: str) -> str:
    user, separator, host = current_user.rpartition("@")
    if not separator or not user or not host:
        raise ConnectorError("connector.invalid_response")
    escaped_user = user.replace("'", "''")
    escaped_host = host.replace("'", "''")
    return f"'{escaped_user}'@'{escaped_host}'"


def _quote_identifier(value: str) -> str:
    return "`" + value.replace("`", "``") + "`"


class MySQLConnector:
    source_type = DataSourceType.MYSQL

    def test_connection(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: NetworkPolicyRules,
    ) -> ConnectionCheck:
        authorized = self._authorized(target, network_rules)
        last_error: Exception | None = None
        for address in authorized:
            try:
                return self._check_address(target, credentials, network_rules, authorized, address)
            except (pymysql.MySQLError, OSError) as exc:
                last_error = exc
        raise self._map_connection_error(last_error)

    def scan_metadata(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: NetworkPolicyRules,
        options: MetadataScanOptions,
    ) -> MetadataDocument:
        if target.database_name.lower() in _SYSTEM_SCHEMAS:
            raise ConnectorError("connector.schema_not_found")
        if options.schemas and (
            len(options.schemas) != 1 or options.schemas[0] != target.database_name
        ):
            raise ConnectorError("connector.schema_not_found")
        authorized = self._authorized(target, network_rules)
        last_error: Exception | None = None
        for address in authorized:
            try:
                return self._scan_address(
                    target, credentials, network_rules, authorized, address, options
                )
            except (pymysql.MySQLError, OSError) as exc:
                last_error = exc
        raise self._map_connection_error(last_error)

    def profile_data(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: NetworkPolicyRules,
        options: ProfileScanOptions,
    ) -> ProfileDocument:
        if target.database_name.lower() in _SYSTEM_SCHEMAS or any(
            table.schema != target.database_name for table in options.tables
        ):
            raise ConnectorError("sampling.scope_invalid")
        authorized = self._authorized(target, network_rules)
        last_error: Exception | None = None
        for address in authorized:
            try:
                return self._profile_address(
                    target, credentials, network_rules, authorized, address, options
                )
            except (pymysql.MySQLError, OSError) as exc:
                last_error = exc
        raise self._map_connection_error(last_error)

    @staticmethod
    def _authorized(
        target: ConnectionTarget, network_rules: NetworkPolicyRules
    ) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        try:
            resolved = resolve_host(target.host)
            return authorize_destination(target.host, target.port, resolved, network_rules)
        except NetworkPolicyError as exc:
            raise ConnectorError(exc.code) from exc

    def _check_address(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: NetworkPolicyRules,
        authorized: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ) -> ConnectionCheck:
        with _connect_address(
            target, credentials, network_rules, authorized, address
        ) as connection:
            _start_read_only(connection)
            with connection.cursor() as cursor:
                cursor.execute("SELECT VERSION(), CURRENT_USER()")
                version_row = cursor.fetchone()
                cursor.execute("SHOW STATUS LIKE 'Ssl_cipher'")
                tls_row = cursor.fetchone()
                if version_row is None or tls_row is None:
                    raise ConnectorError("connector.invalid_response")
                cursor.execute("SELECT ROLE_NAME, ROLE_HOST FROM information_schema.ENABLED_ROLES")
                enabled_roles = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT PRIVILEGE_TYPE FROM information_schema.USER_PRIVILEGES
                    WHERE GRANTEE = %s
                    UNION ALL
                    SELECT PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES
                    WHERE GRANTEE = %s AND TABLE_SCHEMA = %s
                    UNION ALL
                    SELECT PRIVILEGE_TYPE FROM information_schema.TABLE_PRIVILEGES
                    WHERE GRANTEE = %s AND TABLE_SCHEMA = %s
                    UNION ALL
                    SELECT PRIVILEGE_TYPE FROM information_schema.COLUMN_PRIVILEGES
                    WHERE GRANTEE = %s AND TABLE_SCHEMA = %s
                    """,
                    (
                        _grantee(str(version_row[1])),
                        _grantee(str(version_row[1])),
                        target.database_name,
                        _grantee(str(version_row[1])),
                        target.database_name,
                        _grantee(str(version_row[1])),
                        target.database_name,
                    ),
                )
                privilege_rows = cursor.fetchall()
            tls_active = bool(tls_row[1])
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
            privileges = {str(row[0]).upper() for row in privilege_rows}
            if enabled_roles or not privileges or not privileges.issubset(_READ_ONLY_PRIVILEGES):
                raise ConnectorError("connector.read_only_required")
            return ConnectionCheck(
                database_product="mysql",
                database_version=str(version_row[0]),
                connected_address=str(address),
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
        with _connect_address(
            target, credentials, network_rules, authorized, address
        ) as connection:
            _start_read_only(connection)
            with connection.cursor() as cursor:
                cursor.execute("SELECT VERSION(), CURRENT_USER()")
                version_row = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT SCHEMA_NAME, NULL
                    FROM information_schema.SCHEMATA
                    WHERE SCHEMA_NAME = %s
                    """,
                    (target.database_name,),
                )
                schema_rows = list(cursor.fetchall())
                if version_row is None or not schema_rows:
                    raise ConnectorError("connector.schema_not_found")
                relation_rows = self._relations(cursor, target.database_name)
                column_rows = self._columns(cursor, target.database_name)
                constraint_rows = self._constraints(cursor, target.database_name)
                index_rows = self._indexes(cursor, target.database_name)
            count = (
                len(schema_rows)
                + len(relation_rows)
                + len(column_rows)
                + len(constraint_rows)
                + len(index_rows)
            )
            if count > options.max_objects:
                raise ConnectorError("connector.scan_limit_exceeded")
            return self._document(
                str(version_row[0]),
                schema_rows,
                relation_rows,
                column_rows,
                constraint_rows,
                index_rows,
            )

    def _profile_address(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: NetworkPolicyRules,
        authorized: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
        options: ProfileScanOptions,
    ) -> ProfileDocument:
        with _connect_address(
            target, credentials, network_rules, authorized, address
        ) as connection:
            _start_read_only(connection, options.statement_timeout_seconds)
            sampled: list[SampledRelation] = []
            with connection.cursor() as cursor:
                for table in options.tables:
                    cursor.execute(
                        """
                        SELECT TABLE_ROWS FROM information_schema.TABLES
                        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                          AND TABLE_TYPE = 'BASE TABLE'
                        """,
                        (table.schema, table.name),
                    )
                    estimate = cursor.fetchone()
                    if estimate is None:
                        raise ConnectorError("sampling.scope_invalid")
                    selected = tuple(
                        column
                        for column in table.columns
                        if is_sampleable_type(column.data_type, column.native_type)
                    )
                    rows: list[tuple[Any, ...]] = []
                    if selected:
                        selected_sql = ", ".join(
                            _quote_identifier(column.name) for column in selected
                        )
                        query = (
                            f"SELECT {selected_sql} FROM {_quote_identifier(table.schema)}."
                            f"{_quote_identifier(table.name)} "
                            f"LIMIT {options.budget.max_rows_per_table}"
                        )
                        cursor.execute(query)
                        rows = list(cursor.fetchall())
                    values_by_name = {
                        column.name: tuple(row[index] for row in rows)
                        for index, column in enumerate(selected)
                    }
                    sampled.append(
                        SampledRelation(
                            table.schema,
                            table.name,
                            None if estimate[0] is None else int(estimate[0]),
                            tuple(
                                SampledColumn(
                                    column.name,
                                    column.data_type,
                                    column.native_type,
                                    values_by_name.get(column.name, ()),
                                )
                                for column in table.columns
                            ),
                        )
                    )
            return build_profile_document(tuple(sampled), options.budget)

    @staticmethod
    def _relations(cursor: Any, schema: str) -> list[tuple[Any, ...]]:
        cursor.execute(
            """
            SELECT TABLE_SCHEMA, TABLE_NAME,
                   CASE TABLE_TYPE WHEN 'BASE TABLE' THEN 'table' ELSE 'view' END,
                   NULLIF(NULLIF(TABLE_COMMENT, ''), 'VIEW')
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE IN ('BASE TABLE', 'VIEW')
            ORDER BY TABLE_SCHEMA, TABLE_NAME
            """,
            (schema,),
        )
        return list(cursor.fetchall())

    @staticmethod
    def _columns(cursor: Any, schema: str) -> list[tuple[Any, ...]]:
        cursor.execute(
            """
            SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION,
                   COLUMN_TYPE, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
                   NULLIF(COLUMN_COMMENT, '')
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
            """,
            (schema,),
        )
        return list(cursor.fetchall())

    @staticmethod
    def _constraints(cursor: Any, schema: str) -> list[tuple[Any, ...]]:
        cursor.execute(
            """
            SELECT tc.TABLE_SCHEMA, tc.TABLE_NAME, tc.CONSTRAINT_NAME,
                   CASE tc.CONSTRAINT_TYPE
                     WHEN 'PRIMARY KEY' THEN 'primary_key'
                     WHEN 'FOREIGN KEY' THEN 'foreign_key'
                     WHEN 'UNIQUE' THEN 'unique'
                     WHEN 'CHECK' THEN 'check'
                   END,
                   kcu.COLUMN_NAME, kcu.ORDINAL_POSITION,
                   kcu.REFERENCED_TABLE_SCHEMA, kcu.REFERENCED_TABLE_NAME,
                   kcu.REFERENCED_COLUMN_NAME
            FROM information_schema.TABLE_CONSTRAINTS tc
            LEFT JOIN information_schema.KEY_COLUMN_USAGE kcu
              ON kcu.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA
             AND kcu.TABLE_SCHEMA = tc.TABLE_SCHEMA
             AND kcu.TABLE_NAME = tc.TABLE_NAME
             AND kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
            WHERE tc.TABLE_SCHEMA = %s
              AND tc.CONSTRAINT_TYPE IN ('PRIMARY KEY', 'FOREIGN KEY', 'UNIQUE', 'CHECK')
            ORDER BY tc.TABLE_SCHEMA, tc.TABLE_NAME, tc.CONSTRAINT_NAME,
                     kcu.ORDINAL_POSITION
            """,
            (schema,),
        )
        return list(cursor.fetchall())

    @staticmethod
    def _indexes(cursor: Any, schema: str) -> list[tuple[Any, ...]]:
        cursor.execute(
            """
            SELECT TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, NOT NON_UNIQUE,
                   INDEX_TYPE, SEQ_IN_INDEX, COLUMN_NAME, EXPRESSION
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
            """,
            (schema,),
        )
        return list(cursor.fetchall())

    @staticmethod
    def _document(
        version: str,
        schema_rows: list[tuple[Any, ...]],
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
                    nullable=str(row[6]).upper() == "YES",
                    default_expression=None if row[7] is None else str(row[7]),
                    comment=None if row[8] is None else str(row[8]),
                )
            )

        grouped_constraints: dict[
            tuple[str, str, str, str, str | None, str | None],
            tuple[list[str], list[str]],
        ] = {}
        for row in constraint_rows:
            constraint_key = (
                str(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                None if row[6] is None else str(row[6]),
                None if row[7] is None else str(row[7]),
            )
            own, referenced = grouped_constraints.setdefault(constraint_key, ([], []))
            if row[4] is not None:
                own.append(str(row[4]))
            if row[8] is not None:
                referenced.append(str(row[8]))
        constraints: dict[tuple[str, str], list[MetadataConstraint]] = {}
        for constraint_key, (own, referenced) in grouped_constraints.items():
            schema, relation, name, constraint_type, ref_schema, ref_relation = constraint_key
            constraints.setdefault((schema, relation), []).append(
                MetadataConstraint(
                    name=name,
                    constraint_type=constraint_type,
                    columns=tuple(own),
                    referenced_schema=ref_schema,
                    referenced_relation=ref_relation,
                    referenced_columns=tuple(referenced),
                )
            )

        grouped_indexes: dict[tuple[str, str, str, bool, str | None], list[str]] = {}
        for row in index_rows:
            index_key = (
                str(row[0]),
                str(row[1]),
                str(row[2]),
                bool(row[3]),
                None if row[4] is None else str(row[4]).lower(),
            )
            value = row[6] if row[6] is not None else row[7]
            if value is not None:
                grouped_indexes.setdefault(index_key, []).append(str(value))
        indexes: dict[tuple[str, str], list[MetadataIndex]] = {}
        for index_key, names in grouped_indexes.items():
            schema, relation, name, unique, method = index_key
            indexes.setdefault((schema, relation), []).append(
                MetadataIndex(
                    name=name,
                    columns=tuple(names),
                    unique=unique,
                    method=method,
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
            database_product="mysql",
            database_version=version,
            schemas=tuple(
                MetadataSchema(str(row[0]), None if row[1] is None else str(row[1]))
                for row in schema_rows
            ),
            relations=relations,
        )

    @staticmethod
    def _map_connection_error(error: Exception | None) -> ConnectorError:
        if error is None:
            return ConnectorError("connector.connection_failed", retryable=True)
        code = error.args[0] if isinstance(error, pymysql.MySQLError) and error.args else None
        message = str(error).lower()
        if code == 1045:
            return ConnectorError("connector.authentication_failed")
        if code in {1044, 1142, 1143, 1227}:
            return ConnectorError("connector.permission_denied")
        if code in {2026, 2055} or any(word in message for word in ("certificate", "ssl", "tls")):
            return ConnectorError("connector.tls_failed")
        if isinstance(error, (TimeoutError, socket.timeout)) or "timed out" in message:
            return ConnectorError("connector.connection_timeout", retryable=True)
        return ConnectorError("connector.connection_failed", retryable=True)
