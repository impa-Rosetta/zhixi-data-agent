import uuid
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from packages.connectors.metadata import (
    MetadataColumn,
    MetadataConstraint,
    MetadataDocument,
    MetadataIndex,
    MetadataRelation,
    MetadataSchema,
)
from packages.platform_core.catalog import stable_key
from packages.platform_core.models import (
    CatalogColumn,
    CatalogConstraint,
    CatalogIndex,
    CatalogRelation,
    CatalogSchema,
)


def object_counts(document: MetadataDocument) -> dict[str, object]:
    return {
        "schemas": len(document.schemas),
        "relations": len(document.relations),
        "columns": sum(len(item.columns) for item in document.relations),
        "constraints": sum(len(item.constraints) for item in document.relations),
        "indexes": sum(len(item.indexes) for item in document.relations),
    }


def replace_snapshot_document(
    db: Session,
    *,
    snapshot_id: uuid.UUID,
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    document: MetadataDocument,
) -> None:
    for model in (CatalogIndex, CatalogConstraint, CatalogColumn, CatalogRelation, CatalogSchema):
        db.execute(delete(model).where(model.snapshot_id == snapshot_id))

    schema_ids: dict[str, uuid.UUID] = {}
    for schema in document.schemas:
        schema_id = uuid.uuid4()
        schema_ids[schema.name] = schema_id
        db.add(
            CatalogSchema(
                id=schema_id,
                workspace_id=workspace_id,
                data_source_id=data_source_id,
                snapshot_id=snapshot_id,
                stable_key=stable_key("schema", schema.name),
                name=schema.name,
                normalized_name=schema.name.casefold(),
                comment=schema.comment,
            )
        )
    db.flush()

    relation_ids: dict[tuple[str, str], uuid.UUID] = {}
    for relation in document.relations:
        relation_id = uuid.uuid4()
        relation_ids[(relation.schema, relation.name)] = relation_id
        db.add(
            CatalogRelation(
                id=relation_id,
                workspace_id=workspace_id,
                data_source_id=data_source_id,
                snapshot_id=snapshot_id,
                schema_id=schema_ids[relation.schema],
                stable_key=stable_key("relation", relation.schema, relation.name),
                name=relation.name,
                normalized_name=relation.name.casefold(),
                relation_type=relation.relation_type,
                comment=relation.comment,
            )
        )
    db.flush()

    for relation in document.relations:
        relation_id = relation_ids[(relation.schema, relation.name)]
        for column in relation.columns:
            db.add(
                CatalogColumn(
                    workspace_id=workspace_id,
                    data_source_id=data_source_id,
                    snapshot_id=snapshot_id,
                    relation_id=relation_id,
                    stable_key=stable_key("column", relation.schema, relation.name, column.name),
                    name=column.name,
                    normalized_name=column.name.casefold(),
                    ordinal_position=column.ordinal_position,
                    data_type=column.data_type,
                    native_type=column.native_type,
                    nullable=column.nullable,
                    default_expression=column.default_expression,
                    comment=column.comment,
                )
            )
        for constraint in relation.constraints:
            db.add(
                CatalogConstraint(
                    workspace_id=workspace_id,
                    data_source_id=data_source_id,
                    snapshot_id=snapshot_id,
                    relation_id=relation_id,
                    stable_key=stable_key(
                        "constraint", relation.schema, relation.name, constraint.name
                    ),
                    name=constraint.name,
                    constraint_type=constraint.constraint_type,
                    column_names=list(constraint.columns),
                    referenced_schema=constraint.referenced_schema,
                    referenced_relation=constraint.referenced_relation,
                    referenced_columns=list(constraint.referenced_columns),
                )
            )
        for index in relation.indexes:
            db.add(
                CatalogIndex(
                    workspace_id=workspace_id,
                    data_source_id=data_source_id,
                    snapshot_id=snapshot_id,
                    relation_id=relation_id,
                    stable_key=stable_key("index", relation.schema, relation.name, index.name),
                    name=index.name,
                    column_names=list(index.columns),
                    is_unique=index.unique,
                    method=index.method,
                    predicate=index.predicate,
                )
            )


def load_snapshot_document(
    db: Session,
    *,
    snapshot_id: uuid.UUID,
    database_product: str,
    database_version: str | None,
) -> MetadataDocument:
    schema_rows = list(
        db.scalars(
            select(CatalogSchema)
            .where(CatalogSchema.snapshot_id == snapshot_id)
            .order_by(CatalogSchema.name)
        )
    )
    relation_rows = list(
        db.scalars(
            select(CatalogRelation)
            .where(CatalogRelation.snapshot_id == snapshot_id)
            .order_by(CatalogRelation.stable_key)
        )
    )
    columns: dict[uuid.UUID, list[MetadataColumn]] = defaultdict(list)
    for column_row in db.scalars(
        select(CatalogColumn)
        .where(CatalogColumn.snapshot_id == snapshot_id)
        .order_by(CatalogColumn.relation_id, CatalogColumn.ordinal_position)
    ):
        columns[column_row.relation_id].append(
            MetadataColumn(
                name=column_row.name,
                ordinal_position=column_row.ordinal_position,
                data_type=column_row.data_type,
                native_type=column_row.native_type,
                nullable=column_row.nullable,
                default_expression=column_row.default_expression,
                comment=column_row.comment,
            )
        )
    constraints: dict[uuid.UUID, list[MetadataConstraint]] = defaultdict(list)
    for constraint_row in db.scalars(
        select(CatalogConstraint)
        .where(CatalogConstraint.snapshot_id == snapshot_id)
        .order_by(CatalogConstraint.relation_id, CatalogConstraint.name)
    ):
        constraints[constraint_row.relation_id].append(
            MetadataConstraint(
                name=constraint_row.name,
                constraint_type=constraint_row.constraint_type,
                columns=tuple(constraint_row.column_names),
                referenced_schema=constraint_row.referenced_schema,
                referenced_relation=constraint_row.referenced_relation,
                referenced_columns=tuple(constraint_row.referenced_columns),
            )
        )
    indexes: dict[uuid.UUID, list[MetadataIndex]] = defaultdict(list)
    for index_row in db.scalars(
        select(CatalogIndex)
        .where(CatalogIndex.snapshot_id == snapshot_id)
        .order_by(CatalogIndex.relation_id, CatalogIndex.name)
    ):
        indexes[index_row.relation_id].append(
            MetadataIndex(
                name=index_row.name,
                columns=tuple(index_row.column_names),
                unique=index_row.is_unique,
                method=index_row.method,
                predicate=index_row.predicate,
            )
        )
    schema_by_id = {item.id: item.name for item in schema_rows}
    return MetadataDocument(
        database_product=database_product,
        database_version=database_version or "unknown",
        schemas=tuple(MetadataSchema(item.name, item.comment) for item in schema_rows),
        relations=tuple(
            MetadataRelation(
                schema=schema_by_id[item.schema_id],
                name=item.name,
                relation_type=item.relation_type,
                comment=item.comment,
                columns=tuple(columns[item.id]),
                constraints=tuple(constraints[item.id]),
                indexes=tuple(indexes[item.id]),
            )
            for item in relation_rows
        ),
    )
