import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.services.catalogs import get_catalog_source
from apps.api.services.data_sources import DataSourceServiceError
from packages.platform_core.models import (
    CatalogColumn,
    CatalogColumnProfile,
    CatalogRelation,
    CatalogSample,
    CatalogSchema,
    CatalogSnapshot,
    SnapshotStatus,
)
from packages.shared_contracts.data_sources import (
    CatalogColumnProfileResponse,
    CatalogProfileListResponse,
    CatalogSampleResponse,
)


def _snapshot(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> CatalogSnapshot:
    get_catalog_source(db, workspace_id=workspace_id, data_source_id=data_source_id)
    snapshot = db.scalar(
        select(CatalogSnapshot).where(
            CatalogSnapshot.id == snapshot_id,
            CatalogSnapshot.workspace_id == workspace_id,
            CatalogSnapshot.data_source_id == data_source_id,
            CatalogSnapshot.status == SnapshotStatus.PUBLISHED,
        )
    )
    if snapshot is None:
        raise DataSourceServiceError("catalog.not_found", "Published catalog snapshot not found")
    return snapshot


def _response(
    db: Session,
    profile: CatalogColumnProfile,
    column: CatalogColumn,
    relation: CatalogRelation,
    schema: CatalogSchema,
) -> CatalogColumnProfileResponse:
    samples = list(
        db.scalars(
            select(CatalogSample)
            .where(CatalogSample.column_profile_id == profile.id)
            .order_by(CatalogSample.ordinal)
        )
    )
    return CatalogColumnProfileResponse(
        id=profile.id,
        column_id=column.id,
        schema_name=schema.name,
        relation_name=relation.name,
        column_name=column.name,
        data_type=column.data_type,
        native_type=column.native_type,
        sample_row_count=profile.sample_row_count,
        non_null_count=profile.non_null_count,
        estimated_row_count=profile.estimated_row_count,
        sample_null_rate=profile.sample_null_rate,
        sampled_distinct_count=profile.sampled_distinct_count,
        minimum_value=profile.minimum_value,
        maximum_value=profile.maximum_value,
        minimum_length=profile.minimum_length,
        maximum_length=profile.maximum_length,
        average_length=profile.average_length,
        sensitivity_type=profile.sensitivity_type,
        sensitivity_confidence=profile.sensitivity_confidence,
        sensitivity_reasons=profile.sensitivity_reasons,
        metric_sources=profile.metric_sources,
        samples=[CatalogSampleResponse.model_validate(item) for item in samples],
    )


def list_snapshot_profiles(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> CatalogProfileListResponse:
    snapshot = _snapshot(
        db,
        workspace_id=workspace_id,
        data_source_id=data_source_id,
        snapshot_id=snapshot_id,
    )
    rows = list(
        db.execute(
            select(CatalogColumnProfile, CatalogColumn, CatalogRelation, CatalogSchema)
            .join(CatalogColumn, CatalogColumn.id == CatalogColumnProfile.column_id)
            .join(CatalogRelation, CatalogRelation.id == CatalogColumn.relation_id)
            .join(CatalogSchema, CatalogSchema.id == CatalogRelation.schema_id)
            .where(CatalogColumnProfile.snapshot_id == snapshot_id)
            .order_by(CatalogSchema.name, CatalogRelation.name, CatalogColumn.ordinal_position)
        )
    )
    return CatalogProfileListResponse(
        snapshot_id=snapshot.id,
        profiling_status=snapshot.profiling_status,
        profiling_error_code=snapshot.profiling_error_code,
        profile_counts=snapshot.profile_counts,
        items=[_response(db, *row) for row in rows],
    )


def get_snapshot_column_profile(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    column_id: uuid.UUID,
) -> CatalogColumnProfileResponse:
    _snapshot(
        db,
        workspace_id=workspace_id,
        data_source_id=data_source_id,
        snapshot_id=snapshot_id,
    )
    row = db.execute(
        select(CatalogColumnProfile, CatalogColumn, CatalogRelation, CatalogSchema)
        .join(CatalogColumn, CatalogColumn.id == CatalogColumnProfile.column_id)
        .join(CatalogRelation, CatalogRelation.id == CatalogColumn.relation_id)
        .join(CatalogSchema, CatalogSchema.id == CatalogRelation.schema_id)
        .where(
            CatalogColumnProfile.snapshot_id == snapshot_id,
            CatalogColumnProfile.column_id == column_id,
        )
    ).one_or_none()
    if row is None:
        raise DataSourceServiceError("profile.not_found", "Column profile not found")
    return _response(db, *row)
