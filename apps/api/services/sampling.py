import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.services.data_sources import DataSourceServiceError, get_data_source
from packages.platform_core.models import (
    AuditEvent,
    CatalogRelation,
    CatalogSchema,
    SamplingPolicy,
    ScanSchedule,
    ScheduleFrequency,
)
from packages.shared_contracts.data_sources import (
    SamplingPolicyResponse,
    SamplingPolicyUpdateRequest,
    SamplingTableScope,
    ScanScheduleUpdateRequest,
)


def _audit(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    action: str,
    data_source_id: uuid.UUID,
    detail: str,
) -> None:
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type="data_source",
            resource_id=str(data_source_id),
            outcome="success",
            detail=detail,
        )
    )


def get_sampling_policy(
    db: Session, *, workspace_id: uuid.UUID, data_source_id: uuid.UUID
) -> SamplingPolicyResponse:
    get_data_source(db, workspace_id=workspace_id, data_source_id=data_source_id)
    stored = db.get(SamplingPolicy, data_source_id)
    if stored is None or stored.workspace_id != workspace_id:
        return SamplingPolicyResponse(
            data_source_id=data_source_id,
            enabled=False,
            schema_allowlist=[],
            table_allowlist=[],
            max_rows_per_table=20,
            max_values_per_column=20,
            max_value_chars=256,
            max_bytes_per_table=65_536,
            max_bytes_per_job=1_048_576,
            statement_timeout_seconds=10,
            version=0,
            updated_at=None,
        )
    return SamplingPolicyResponse.model_validate(stored)


def _validate_catalog_scope(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    snapshot_id: uuid.UUID | None,
    schemas: list[str],
    tables: list[SamplingTableScope],
) -> None:
    if not schemas and not tables:
        return
    if snapshot_id is None:
        raise DataSourceServiceError(
            "sampling.catalog_required", "Publish a catalog before selecting sampling tables"
        )
    available = {
        (schema.name, relation.name)
        for relation, schema in db.execute(
            select(CatalogRelation, CatalogSchema)
            .join(CatalogSchema, CatalogSchema.id == CatalogRelation.schema_id)
            .where(
                CatalogRelation.workspace_id == workspace_id,
                CatalogRelation.data_source_id == data_source_id,
                CatalogRelation.snapshot_id == snapshot_id,
                CatalogRelation.relation_type == "table",
            )
        )
    }
    requested = {(item.schema_name, item.table_name) for item in tables}
    available_schemas = {schema for schema, _ in available}
    if not set(schemas).issubset(available_schemas) or not requested.issubset(available):
        raise DataSourceServiceError(
            "sampling.scope_invalid", "Sampling scope must contain published ordinary tables"
        )


def update_sampling_policy(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: SamplingPolicyUpdateRequest,
) -> SamplingPolicy:
    source = get_data_source(db, workspace_id=workspace_id, data_source_id=data_source_id)
    stored = db.get(SamplingPolicy, data_source_id)
    current_version = stored.version if stored is not None else 0
    if payload.version != current_version:
        raise DataSourceServiceError(
            "sampling.version_conflict", "Sampling policy changed; refresh before retrying"
        )
    _validate_catalog_scope(
        db,
        workspace_id=workspace_id,
        data_source_id=data_source_id,
        snapshot_id=source.active_snapshot_id,
        schemas=payload.schema_allowlist,
        tables=payload.table_allowlist,
    )
    if stored is None:
        stored = SamplingPolicy(
            data_source_id=data_source_id,
            workspace_id=workspace_id,
            updated_by_user_id=actor_user_id,
        )
        db.add(stored)
    stored.enabled = payload.enabled
    stored.schema_allowlist = list(payload.schema_allowlist)
    stored.table_allowlist = [item.model_dump() for item in payload.table_allowlist]
    stored.max_rows_per_table = payload.max_rows_per_table
    stored.max_values_per_column = payload.max_values_per_column
    stored.max_value_chars = payload.max_value_chars
    stored.max_bytes_per_table = payload.max_bytes_per_table
    stored.max_bytes_per_job = payload.max_bytes_per_job
    stored.statement_timeout_seconds = payload.statement_timeout_seconds
    stored.version = current_version + 1
    stored.updated_by_user_id = actor_user_id
    _audit(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action="data_source.sampling_policy.update",
        data_source_id=data_source_id,
        detail=(
            f"enabled={str(payload.enabled).lower()};schemas={len(payload.schema_allowlist)};"
            f"tables={len(payload.table_allowlist)};version={stored.version}"
        ),
    )
    db.flush()
    return stored


def _valid_local_candidate(local_day: date, payload: ScanScheduleUpdateRequest) -> datetime:
    zone = ZoneInfo(payload.timezone)
    naive = datetime.combine(local_day, payload.local_time)
    candidate = naive.replace(tzinfo=zone, fold=0)
    round_trip = candidate.astimezone(UTC).astimezone(zone)
    if round_trip.replace(tzinfo=None) == naive:
        return candidate
    for minutes in range(1, 181):
        shifted = naive + timedelta(minutes=minutes)
        candidate = shifted.replace(tzinfo=zone, fold=0)
        round_trip = candidate.astimezone(UTC).astimezone(zone)
        if round_trip.replace(tzinfo=None) == shifted:
            return candidate
    raise DataSourceServiceError(
        "schedule.invalid_expression", "No valid local execution time could be resolved"
    )


def next_schedule_run(
    payload: ScanScheduleUpdateRequest, *, now: datetime | None = None
) -> datetime | None:
    if not payload.enabled:
        return None
    current = (now or datetime.now(UTC)).astimezone(ZoneInfo(payload.timezone))
    local_day = current.date()
    if payload.frequency is ScheduleFrequency.WEEKLY:
        assert payload.day_of_week is not None
        local_day += timedelta(days=(payload.day_of_week - local_day.weekday()) % 7)
    candidate = _valid_local_candidate(local_day, payload)
    if candidate <= current:
        interval = 1 if payload.frequency is ScheduleFrequency.DAILY else 7
        candidate = _valid_local_candidate(local_day + timedelta(days=interval), payload)
    return candidate.astimezone(UTC)


def get_scan_schedule(
    db: Session, *, workspace_id: uuid.UUID, data_source_id: uuid.UUID
) -> ScanSchedule:
    get_data_source(db, workspace_id=workspace_id, data_source_id=data_source_id)
    stored = db.get(ScanSchedule, data_source_id)
    if stored is None or stored.workspace_id != workspace_id:
        raise DataSourceServiceError("schedule.not_configured", "Scan schedule is not configured")
    return stored


def update_scan_schedule(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: ScanScheduleUpdateRequest,
    now: datetime | None = None,
) -> ScanSchedule:
    get_data_source(db, workspace_id=workspace_id, data_source_id=data_source_id)
    stored = db.get(ScanSchedule, data_source_id)
    current_version = stored.version if stored is not None else 0
    if payload.version != current_version:
        raise DataSourceServiceError(
            "schedule.version_conflict", "Scan schedule changed; refresh before retrying"
        )
    if stored is None:
        stored = ScanSchedule(
            data_source_id=data_source_id,
            workspace_id=workspace_id,
            frequency=payload.frequency,
            timezone=payload.timezone,
            local_time=payload.local_time,
            updated_by_user_id=actor_user_id,
        )
        db.add(stored)
    stored.enabled = payload.enabled
    stored.frequency = payload.frequency
    stored.timezone = payload.timezone
    stored.local_time = payload.local_time
    stored.day_of_week = payload.day_of_week
    stored.next_run_at = next_schedule_run(payload, now=now)
    stored.version = current_version + 1
    stored.updated_by_user_id = actor_user_id
    _audit(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action="data_source.schedule.update",
        data_source_id=data_source_id,
        detail=(
            f"enabled={str(payload.enabled).lower()};frequency={payload.frequency.value};"
            f"version={stored.version}"
        ),
    )
    db.flush()
    return stored
