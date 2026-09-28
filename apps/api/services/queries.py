import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlglot import exp, parse_one

from apps.api.audit import add_audit_event
from packages.connectors.base import ConnectionTarget, ConnectorError
from packages.platform_core.data_source_runtime import load_runtime_credentials
from packages.platform_core.models import (
    CatalogColumn,
    CatalogColumnProfile,
    CatalogRelation,
    CatalogSchema,
    CatalogSnapshot,
    DataSource,
    DataSourceStatus,
)
from packages.platform_core.settings import get_settings
from packages.query_engine.compiler import (
    QueryCompilationError,
    ResolvedAttribute,
    compile_semantic_query,
)
from packages.query_engine.models import (
    QueryExecution,
    QueryExecutionStatus,
    QueryTrust,
    ValidatedQuery,
)
from packages.query_engine.runtime import execute_read_only
from packages.query_engine.security import QuerySecurityError, validate_sql
from packages.semantic_model.models import (
    SemanticModel,
    SemanticModelVersion,
    SemanticVersionStatus,
)
from packages.shared_contracts.queries import (
    ExploratoryQueryRequest,
    QueryExecutionResponse,
    SemanticQueryRequest,
    ValidatedQueryResponse,
)
from packages.shared_contracts.semantic_models import SemanticDocument


class QueryServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _response(item: ValidatedQuery) -> ValidatedQueryResponse:
    return ValidatedQueryResponse(
        id=item.id,
        workspace_id=item.workspace_id,
        data_source_id=item.data_source_id,
        semantic_model_id=item.semantic_model_id,
        semantic_version_id=item.semantic_version_id,
        snapshot_id=item.snapshot_id,
        dialect="postgres" if item.dialect == "postgres" else "mysql",
        trust=item.trust.value,
        sql=item.sql_text,
        parameter_count=len(item.parameters),
        dependencies=list(item.dependencies),
        digest=item.digest,
        safety_findings=[],
        expires_at=item.expires_at,
        created_at=item.created_at,
    )


def _execution_response(item: QueryExecution, query: ValidatedQuery) -> QueryExecutionResponse:
    return QueryExecutionResponse(
        id=item.id,
        validated_query_id=item.validated_query_id,
        status=item.status.value,
        columns=list(item.columns),
        rows=[list(row) for row in item.rows],
        row_count=item.row_count,
        truncated=item.truncated,
        trust=query.trust.value,
        evidence_digest=item.evidence_digest,
        error_code=item.error_code,
        started_at=item.started_at,
        finished_at=item.finished_at,
    )


def _dialect(source: DataSource) -> str:
    return "postgres" if source.source_type.value == "postgresql" else "mysql"


def _source_snapshot(
    db: Session, workspace_id: uuid.UUID, source_id: uuid.UUID
) -> tuple[DataSource, CatalogSnapshot]:
    source = db.scalar(
        select(DataSource).where(
            DataSource.id == source_id,
            DataSource.workspace_id == workspace_id,
            DataSource.deleted_at.is_(None),
        )
    )
    if (
        source is None
        or source.status not in {DataSourceStatus.READY, DataSourceStatus.DEGRADED}
        or source.active_snapshot_id is None
    ):
        raise QueryServiceError(
            "query.data_source_unavailable", "Data source is not ready for governed queries"
        )
    snapshot = db.get(CatalogSnapshot, source.active_snapshot_id)
    if snapshot is None or snapshot.workspace_id != workspace_id:
        raise QueryServiceError(
            "query.snapshot_not_found", "Active catalog snapshot is unavailable"
        )
    return source, snapshot


def _catalog_relations(db: Session, snapshot_id: uuid.UUID) -> set[str]:
    rows = db.execute(
        select(CatalogSchema.name, CatalogRelation.name)
        .join(CatalogRelation, CatalogRelation.schema_id == CatalogSchema.id)
        .where(CatalogSchema.snapshot_id == snapshot_id)
    ).all()
    return {f"{schema}.{relation}" for schema, relation in rows}


def compile_query(
    db: Session, *, workspace_id: uuid.UUID, actor_user_id: uuid.UUID, payload: SemanticQueryRequest
) -> ValidatedQueryResponse:
    model = db.scalar(
        select(SemanticModel).where(
            SemanticModel.id == payload.semantic_model_id,
            SemanticModel.workspace_id == workspace_id,
        )
    )
    if model is None or model.active_version_id is None:
        raise QueryServiceError(
            "query.semantic_model_unpublished", "A published semantic model is required"
        )
    version = db.get(SemanticModelVersion, model.active_version_id)
    if version is None or version.status is not SemanticVersionStatus.PUBLISHED:
        raise QueryServiceError(
            "query.semantic_model_unpublished", "A published semantic model is required"
        )
    document = SemanticDocument.model_validate(version.document)
    resolved: dict[str, ResolvedAttribute] = {}
    source_ids: set[uuid.UUID] = set()
    snapshot_ids: set[uuid.UUID] = set()
    for mapping in document.mappings:
        if not mapping.confirmed:
            continue
        row = db.execute(
            select(
                CatalogSchema.name,
                CatalogRelation.name,
                CatalogColumn.name,
                CatalogColumn.data_source_id,
            )
            .join(CatalogRelation, CatalogRelation.schema_id == CatalogSchema.id)
            .join(CatalogColumn, CatalogColumn.relation_id == CatalogRelation.id)
            .where(
                CatalogColumn.id == mapping.column_id,
                CatalogColumn.relation_id == mapping.relation_id,
                CatalogColumn.snapshot_id == mapping.snapshot_id,
                CatalogColumn.workspace_id == workspace_id,
            )
        ).one_or_none()
        if row is None:
            raise QueryServiceError(
                "query.mapping_stale", "A semantic mapping no longer resolves in the frozen catalog"
            )
        resolved[mapping.semantic_attribute] = ResolvedAttribute(
            mapping.semantic_attribute, row[0], row[1], row[2]
        )
        source_ids.add(row[3])
        snapshot_ids.add(mapping.snapshot_id)
    if len(source_ids) != 1 or len(snapshot_ids) != 1:
        raise QueryServiceError(
            "query.mapping_scope_invalid",
            "A query must resolve to one data source and catalog snapshot",
        )
    source, snapshot = _source_snapshot(db, workspace_id, next(iter(source_ids)))
    if snapshot.id != next(iter(snapshot_ids)):
        raise QueryServiceError(
            "query.snapshot_stale", "Semantic model must be remapped to the active catalog snapshot"
        )
    try:
        compiled = compile_semantic_query(payload, document, resolved, dialect=_dialect(source))
        report = validate_sql(
            compiled.sql, dialect=_dialect(source), allowed_relations=set(compiled.relations)
        )
    except (QueryCompilationError, QuerySecurityError) as exc:
        raise QueryServiceError(exc.code, exc.message) from exc
    now = datetime.now(UTC)
    item = ValidatedQuery(
        workspace_id=workspace_id,
        data_source_id=source.id,
        snapshot_id=snapshot.id,
        semantic_model_id=model.id,
        semantic_version_id=version.id,
        dialect=_dialect(source),
        trust=QueryTrust.TRUSTED,
        protocol=payload.model_dump(mode="json"),
        sql_text=report.normalized_sql,
        parameters=[_json_value(value) for value in compiled.parameters],
        dependencies=list(report.dependencies),
        safety_report={"engine": "sqlglot", "outcome": "approved"},
        digest=report.digest,
        row_limit=payload.limit,
        created_by_user_id=actor_user_id,
        expires_at=now + timedelta(minutes=15),
        created_at=now,
    )
    db.add(item)
    db.flush()
    add_audit_event(
        db,
        action="query.compile",
        outcome="success",
        resource_type="validated_query",
        resource_id=str(item.id),
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        detail=f"trusted:{item.digest}",
    )
    return _response(item)


def validate_exploratory_query(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: ExploratoryQueryRequest,
) -> ValidatedQueryResponse:
    source, snapshot = _source_snapshot(db, workspace_id, payload.data_source_id)
    allowed = _catalog_relations(db, snapshot.id)
    try:
        initial = validate_sql(payload.sql, dialect=_dialect(source), allowed_relations=allowed)
        expression = parse_one(initial.normalized_sql, read=_dialect(source))
        if not isinstance(expression, exp.Query):
            raise QueryServiceError("query.read_only_required", "Only SELECT is allowed")
        expression = expression.limit(payload.limit + 1)
        report = validate_sql(
            expression.sql(dialect=_dialect(source)),
            dialect=_dialect(source),
            allowed_relations=allowed,
        )
    except QuerySecurityError as exc:
        raise QueryServiceError(exc.code, exc.message) from exc
    except ValueError as exc:
        raise QueryServiceError("query.parse_failed", "SQL could not be parsed") from exc
    now = datetime.now(UTC)
    item = ValidatedQuery(
        workspace_id=workspace_id,
        data_source_id=source.id,
        snapshot_id=snapshot.id,
        semantic_model_id=None,
        semantic_version_id=None,
        dialect=_dialect(source),
        trust=QueryTrust.EXPLORATORY,
        protocol=payload.model_dump(mode="json"),
        sql_text=report.normalized_sql,
        parameters=[],
        dependencies=list(report.dependencies),
        safety_report={"engine": "sqlglot", "outcome": "approved", "warning": "exploratory_sql"},
        digest=report.digest,
        row_limit=payload.limit,
        created_by_user_id=actor_user_id,
        expires_at=now + timedelta(minutes=10),
        created_at=now,
    )
    db.add(item)
    db.flush()
    add_audit_event(
        db,
        action="query.validate_exploratory",
        outcome="success",
        resource_type="validated_query",
        resource_id=str(item.id),
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        detail=f"exploratory:{item.digest}",
    )
    return _response(item)


def _sensitive_output_names(
    db: Session, item: ValidatedQuery, columns: tuple[str, ...]
) -> set[str]:
    profiles = db.execute(
        select(CatalogColumn.name, CatalogColumnProfile.column_id)
        .join(CatalogColumnProfile, CatalogColumnProfile.column_id == CatalogColumn.id)
        .where(
            CatalogColumnProfile.snapshot_id == item.snapshot_id,
            CatalogColumnProfile.sensitivity_type.is_not(None),
        )
    ).all()
    sensitive_names = {name.lower() for name, _ in profiles}
    output_names = {name for name in columns if name.lower() in sensitive_names}
    if item.semantic_version_id is None:
        return output_names
    version = db.get(SemanticModelVersion, item.semantic_version_id)
    if version is None:
        return output_names
    document = SemanticDocument.model_validate(version.document)
    sensitive_ids = {column_id for _, column_id in profiles}
    mapping_by_ref = {mapping.semantic_attribute: mapping for mapping in document.mappings}
    dimension_by_key = {dimension.key: dimension for dimension in document.dimensions}
    selected = item.protocol.get("dimensions", [])
    if isinstance(selected, list):
        for key in selected:
            dimension = dimension_by_key.get(str(key))
            if dimension is None:
                continue
            mapping = mapping_by_ref.get(f"{dimension.entity_key}.{dimension.attribute_key}")
            if mapping is not None and mapping.column_id in sensitive_ids:
                output_names.add(dimension.key)
    return output_names


def _mask_rows(
    columns: tuple[str, ...], rows: list[list[object]], sensitive: set[str]
) -> list[list[object]]:
    positions = {index for index, name in enumerate(columns) if name in sensitive}
    return [
        [
            "***MASKED***" if index in positions and value is not None else value
            for index, value in enumerate(row)
        ]
        for row in rows
    ]


def execute_query(
    db: Session, *, workspace_id: uuid.UUID, actor_user_id: uuid.UUID, validated_query_id: uuid.UUID
) -> QueryExecutionResponse:
    item = db.scalar(
        select(ValidatedQuery).where(
            ValidatedQuery.id == validated_query_id, ValidatedQuery.workspace_id == workspace_id
        )
    )
    if item is None:
        raise QueryServiceError("query.not_found", "Validated query not found")
    now = datetime.now(UTC)
    expires_at = item.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        raise QueryServiceError(
            "query.validation_expired", "Validated query has expired; validate it again"
        )
    source, snapshot = _source_snapshot(db, workspace_id, item.data_source_id)
    if snapshot.id != item.snapshot_id:
        raise QueryServiceError(
            "query.snapshot_changed", "Catalog changed after validation; validate the query again"
        )
    credentials, rules = load_runtime_credentials(db, source, get_settings())
    started = datetime.now(UTC)
    try:
        result = execute_read_only(
            source.source_type,
            ConnectionTarget(source.host, source.port, source.database_name, source.tls_mode),
            credentials,
            rules,
            item.sql_text,
            tuple(item.parameters),
            row_limit=item.row_limit,
        )
        rows = _mask_rows(
            result.columns,
            [list(row) for row in result.rows],
            _sensitive_output_names(db, item, result.columns),
        )
        canonical = json.dumps(
            {"columns": result.columns, "rows": rows},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        result_digest = hashlib.sha256(canonical.encode()).hexdigest()
        evidence = {
            "validated_query_id": str(item.id),
            "query_digest": item.digest,
            "result_digest": result_digest,
            "snapshot_id": str(item.snapshot_id),
            "semantic_version_id": None
            if item.semantic_version_id is None
            else str(item.semantic_version_id),
            "dependencies": item.dependencies,
            "trust": item.trust.value,
            "executed_at": started.isoformat(),
        }
        evidence_digest = hashlib.sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        execution = QueryExecution(
            workspace_id=workspace_id,
            validated_query_id=item.id,
            status=QueryExecutionStatus.SUCCEEDED,
            columns=list(result.columns),
            rows=rows,
            row_count=len(rows),
            truncated=result.truncated,
            result_digest=result_digest,
            evidence_digest=evidence_digest,
            evidence=evidence,
            error_code=None,
            requested_by_user_id=actor_user_id,
            started_at=started,
            finished_at=datetime.now(UTC),
        )
    except ConnectorError as exc:
        execution = QueryExecution(
            workspace_id=workspace_id,
            validated_query_id=item.id,
            status=QueryExecutionStatus.FAILED,
            columns=[],
            rows=[],
            row_count=0,
            truncated=False,
            result_digest=None,
            evidence_digest=None,
            evidence={
                "query_digest": item.digest,
                "snapshot_id": str(item.snapshot_id),
                "trust": item.trust.value,
            },
            error_code=exc.code,
            requested_by_user_id=actor_user_id,
            started_at=started,
            finished_at=datetime.now(UTC),
        )
    db.add(execution)
    db.flush()
    add_audit_event(
        db,
        action="query.execute",
        outcome="success" if execution.status is QueryExecutionStatus.SUCCEEDED else "failure",
        resource_type="query_execution",
        resource_id=str(execution.id),
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        detail=f"{item.trust.value}:{execution.error_code or execution.evidence_digest}",
    )
    return _execution_response(execution, item)


def list_executions(
    db: Session, *, workspace_id: uuid.UUID, limit: int = 50
) -> list[QueryExecutionResponse]:
    rows = db.execute(
        select(QueryExecution, ValidatedQuery)
        .join(ValidatedQuery, ValidatedQuery.id == QueryExecution.validated_query_id)
        .where(QueryExecution.workspace_id == workspace_id)
        .order_by(QueryExecution.started_at.desc())
        .limit(limit)
    ).all()
    return [_execution_response(execution, query) for execution, query in rows]


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)
