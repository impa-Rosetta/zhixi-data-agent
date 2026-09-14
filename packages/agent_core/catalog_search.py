"""Authorized, metadata-only search over published catalog snapshots."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.platform_core.catalog_store import load_snapshot_document
from packages.platform_core.models import CatalogSnapshot, DataSource, SnapshotStatus


class CatalogSearchError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def search_published_catalogs(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    query: str,
    max_sources: int = 10,
    max_relations: int = 25,
    max_columns_per_relation: int = 50,
) -> dict[str, object]:
    rows = db.execute(
        select(DataSource, CatalogSnapshot)
        .join(CatalogSnapshot, DataSource.active_snapshot_id == CatalogSnapshot.id)
        .where(
            DataSource.workspace_id == workspace_id,
            DataSource.deleted_at.is_(None),
            CatalogSnapshot.workspace_id == workspace_id,
            CatalogSnapshot.status == SnapshotStatus.PUBLISHED,
        )
        .order_by(DataSource.name, DataSource.id)
        .limit(max_sources + 1)
    ).all()
    if not rows:
        raise CatalogSearchError("catalog.not_available")

    normalized = query.strip().casefold()
    broad = not normalized or any(
        phrase in normalized
        for phrase in (
            "有哪些数据",
            "什么数据",
            "有什么数据",
            "数据源",
            "数据库",
            "有哪些表",
            "有什么表",
            "所有表",
            "全部表",
            "表里有啥",
            "表格",
        )
    )
    sources: list[dict[str, object]] = []
    total_matches = 0
    returned_relations = 0
    truncated = len(rows) > max_sources
    for source, snapshot in rows[:max_sources]:
        document = load_snapshot_document(
            db,
            snapshot_id=snapshot.id,
            database_product=snapshot.database_product,
            database_version=snapshot.database_version,
        )
        relation_items: list[dict[str, object]] = []
        source_matches = normalized in source.name.casefold()
        for relation in document.relations:
            object_mentioned = any(
                name and name.casefold() in normalized
                for name in (
                    relation.schema,
                    relation.name,
                    *(column.name for column in relation.columns),
                )
            )
            searchable = " ".join(
                (
                    relation.schema,
                    relation.name,
                    relation.comment or "",
                    *(column.name for column in relation.columns),
                    *(column.comment or "" for column in relation.columns),
                )
            ).casefold()
            if not (broad or source_matches or object_mentioned or normalized in searchable):
                continue
            total_matches += 1
            if returned_relations >= max_relations:
                truncated = True
                continue
            columns = relation.columns[:max_columns_per_relation]
            if len(relation.columns) > max_columns_per_relation:
                truncated = True
            relation_items.append(
                {
                    "schema": relation.schema,
                    "name": relation.name,
                    "relation_type": relation.relation_type,
                    "comment": relation.comment,
                    "column_count": len(relation.columns),
                    "columns": [
                        {
                            "name": column.name,
                            "data_type": column.data_type,
                            "nullable": column.nullable,
                            "comment": column.comment,
                        }
                        for column in columns
                    ],
                }
            )
            returned_relations += 1
        if relation_items or broad or source_matches:
            sources.append(
                {
                    "id": str(source.id),
                    "name": source.name,
                    "source_type": source.source_type.value,
                    "snapshot_id": str(snapshot.id),
                    "snapshot_version": snapshot.version,
                    "snapshot_digest": snapshot.content_digest,
                    "database_product": snapshot.database_product,
                    "relations": relation_items,
                }
            )

    message = (
        f"在当前工作空间的已发布目录中找到 {len(sources)} 个数据源、"
        f"{returned_relations} 个匹配的表或视图。"
        if sources
        else "当前已发布目录中没有匹配的数据对象，请换一个表名、字段名或数据源名称。"
    )
    return {
        "message": message,
        "query": query,
        "source_count": len(sources),
        "relation_count": returned_relations,
        "total_matches": total_matches,
        "sources": sources,
        "truncated": truncated,
        "samples_included": False,
        "trust": "catalog",
    }
