import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.services.data_sources import DataSourceServiceError
from packages.connectors.metadata import MetadataDocument
from packages.platform_core.catalog_store import load_snapshot_document
from packages.platform_core.models import (
    CatalogDiff,
    CatalogSnapshot,
    DataSource,
    SnapshotStatus,
)


def get_catalog_source(
    db: Session, *, workspace_id: uuid.UUID, data_source_id: uuid.UUID
) -> DataSource:
    source = db.scalar(
        select(DataSource).where(
            DataSource.id == data_source_id,
            DataSource.workspace_id == workspace_id,
            DataSource.deleted_at.is_(None),
        )
    )
    if source is None:
        raise DataSourceServiceError("data_source.not_found", "Data source not found")
    return source


def list_snapshots(
    db: Session, *, workspace_id: uuid.UUID, data_source_id: uuid.UUID
) -> list[CatalogSnapshot]:
    get_catalog_source(db, workspace_id=workspace_id, data_source_id=data_source_id)
    return list(
        db.scalars(
            select(CatalogSnapshot)
            .where(
                CatalogSnapshot.workspace_id == workspace_id,
                CatalogSnapshot.data_source_id == data_source_id,
            )
            .order_by(CatalogSnapshot.version.desc())
        )
    )


def get_catalog(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    snapshot_id: uuid.UUID | None,
) -> tuple[CatalogSnapshot, MetadataDocument]:
    source = get_catalog_source(db, workspace_id=workspace_id, data_source_id=data_source_id)
    selected_id = snapshot_id or source.active_snapshot_id
    if selected_id is None:
        raise DataSourceServiceError("catalog.not_available", "No published catalog is available")
    snapshot = db.scalar(
        select(CatalogSnapshot).where(
            CatalogSnapshot.id == selected_id,
            CatalogSnapshot.workspace_id == workspace_id,
            CatalogSnapshot.data_source_id == data_source_id,
            CatalogSnapshot.status == SnapshotStatus.PUBLISHED,
        )
    )
    if snapshot is None:
        raise DataSourceServiceError("catalog.not_found", "Published catalog snapshot not found")
    return snapshot, load_snapshot_document(
        db,
        snapshot_id=snapshot.id,
        database_product=snapshot.database_product,
        database_version=snapshot.database_version,
    )


def list_diffs(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    to_snapshot_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[CatalogDiff], int]:
    source = get_catalog_source(db, workspace_id=workspace_id, data_source_id=data_source_id)
    selected_id = to_snapshot_id or source.active_snapshot_id
    if selected_id is None:
        return [], 0
    filters = (
        CatalogDiff.workspace_id == workspace_id,
        CatalogDiff.data_source_id == data_source_id,
        CatalogDiff.to_snapshot_id == selected_id,
    )
    total = db.scalar(select(func.count()).select_from(CatalogDiff).where(*filters)) or 0
    items = list(
        db.scalars(
            select(CatalogDiff)
            .where(*filters)
            .order_by(CatalogDiff.object_key, CatalogDiff.change_type)
            .offset(offset)
            .limit(limit)
        )
    )
    return items, total
