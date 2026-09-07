import hashlib
import json
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.audit import add_audit_event
from packages.platform_core.models import (
    CatalogColumn,
    CatalogRelation,
    CatalogSchema,
    CatalogSnapshot,
)
from packages.semantic_model.models import (
    SemanticModel,
    SemanticModelStatus,
    SemanticModelVersion,
    SemanticVersionStatus,
)
from packages.shared_contracts.semantic_models import (
    MappingCandidate,
    MappingCandidateResponse,
    SemanticDocument,
    SemanticDraftUpdateRequest,
    SemanticModelResponse,
)


class SemanticModelServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _digest(document: dict[str, object]) -> str:
    canonical = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _counts(document: SemanticDocument) -> dict[str, int]:
    return {
        "entities": len(document.entities),
        "attributes": sum(len(entity.attributes) for entity in document.entities),
        "relationships": len(document.relationships),
        "dimensions": len(document.dimensions),
        "metrics": len(document.metrics),
        "mappings": len(document.mappings),
    }


def _get_model(db: Session, workspace_id: uuid.UUID, model_id: uuid.UUID) -> SemanticModel:
    model = db.scalar(
        select(SemanticModel).where(
            SemanticModel.id == model_id, SemanticModel.workspace_id == workspace_id
        )
    )
    if model is None:
        raise SemanticModelServiceError("semantic_model.not_found", "Semantic model not found")
    return model


def _current_version(db: Session, model: SemanticModel) -> SemanticModelVersion:
    version = db.scalar(
        select(SemanticModelVersion)
        .where(SemanticModelVersion.semantic_model_id == model.id)
        .order_by(SemanticModelVersion.revision.desc())
    )
    if version is None:
        raise SemanticModelServiceError("semantic_model.corrupt", "Semantic model has no version")
    return version


def _validate_references(document: SemanticDocument) -> None:
    attributes = {
        f"{entity.key}.{attribute.key}"
        for entity in document.entities
        for attribute in entity.attributes
    }
    entities = {item.key for item in document.entities}
    dimensions = {item.key for item in document.dimensions}
    for relation in document.relationships:
        if relation.from_attribute not in attributes or relation.to_attribute not in attributes:
            raise SemanticModelServiceError(
                "semantic_model.invalid_reference",
                f"Relationship {relation.key} references an unknown attribute",
            )
    for dimension in document.dimensions:
        if (
            dimension.entity_key not in entities
            or f"{dimension.entity_key}.{dimension.attribute_key}" not in attributes
        ):
            raise SemanticModelServiceError(
                "semantic_model.invalid_reference",
                f"Dimension {dimension.key} references an unknown attribute",
            )
    for metric in document.metrics:
        formula_refs = [
            metric.formula.attribute,
            metric.formula.numerator,
            metric.formula.denominator,
        ]
        if any(ref is not None and ref not in attributes for ref in formula_refs):
            raise SemanticModelServiceError(
                "semantic_model.invalid_reference",
                f"Metric {metric.key} references an unknown attribute",
            )
        if any(key not in dimensions for key in metric.supported_dimensions):
            raise SemanticModelServiceError(
                "semantic_model.invalid_reference",
                f"Metric {metric.key} references an unknown dimension",
            )
    if any(mapping.semantic_attribute not in attributes for mapping in document.mappings):
        raise SemanticModelServiceError(
            "semantic_model.invalid_reference",
            "A physical mapping references an unknown semantic attribute",
        )


def _validate_physical_mappings(
    db: Session, workspace_id: uuid.UUID, document: SemanticDocument, *, publishing: bool
) -> None:
    for mapping in document.mappings:
        column = db.scalar(
            select(CatalogColumn).where(
                CatalogColumn.id == mapping.column_id,
                CatalogColumn.relation_id == mapping.relation_id,
                CatalogColumn.snapshot_id == mapping.snapshot_id,
                CatalogColumn.workspace_id == workspace_id,
            )
        )
        if column is None:
            raise SemanticModelServiceError(
                "semantic_model.mapping_not_found",
                "A mapping does not belong to this workspace catalog",
            )
        if publishing and not mapping.confirmed:
            raise SemanticModelServiceError(
                "semantic_model.mapping_unconfirmed",
                "Every physical mapping must be confirmed before publishing",
            )


def _response(db: Session, model: SemanticModel) -> SemanticModelResponse:
    version = _current_version(db, model)
    active = (
        db.get(SemanticModelVersion, model.active_version_id) if model.active_version_id else None
    )
    return SemanticModelResponse(
        id=model.id,
        workspace_id=model.workspace_id,
        name=model.name,
        description=model.description,
        status=model.status.value,
        version=model.version,
        draft_revision=version.revision,
        published_version=active.revision if active is not None else None,
        counts=dict(version.counts),
        document=SemanticDocument.model_validate(version.document),
        content_digest=version.content_digest,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def create_semantic_model(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str,
    description: str | None,
    document: SemanticDocument | None = None,
) -> SemanticModelResponse:
    doc = document or SemanticDocument()
    _validate_references(doc)
    stored_doc = doc.model_dump(mode="json")
    model = SemanticModel(
        workspace_id=workspace_id,
        name=name,
        description=description,
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
    )
    db.add(model)
    db.flush()
    version = SemanticModelVersion(
        workspace_id=workspace_id,
        semantic_model_id=model.id,
        revision=1,
        status=SemanticVersionStatus.DRAFT,
        document=stored_doc,
        counts=_counts(doc),
        content_digest=_digest(stored_doc),
        created_by_user_id=actor_user_id,
    )
    db.add(version)
    db.flush()
    add_audit_event(
        db,
        action="semantic_model.created",
        outcome="success",
        resource_type="semantic_model",
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        resource_id=str(model.id),
    )
    return _response(db, model)


def list_semantic_models(db: Session, *, workspace_id: uuid.UUID) -> list[SemanticModelResponse]:
    models = db.scalars(
        select(SemanticModel)
        .where(SemanticModel.workspace_id == workspace_id)
        .order_by(SemanticModel.updated_at.desc())
    ).all()
    return [_response(db, model) for model in models]


def get_semantic_model(
    db: Session, *, workspace_id: uuid.UUID, model_id: uuid.UUID
) -> SemanticModelResponse:
    return _response(db, _get_model(db, workspace_id, model_id))


def update_semantic_draft(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    model_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: SemanticDraftUpdateRequest,
) -> SemanticModelResponse:
    model = _get_model(db, workspace_id, model_id)
    if model.status != SemanticModelStatus.DRAFT:
        raise SemanticModelServiceError(
            "semantic_model.immutable", "Published semantic models are immutable"
        )
    if model.version != payload.version:
        raise SemanticModelServiceError(
            "semantic_model.version_conflict", "Semantic model changed; refresh before retrying"
        )
    document = SemanticDocument.model_validate(payload.model_dump(exclude={"version"}))
    _validate_references(document)
    _validate_physical_mappings(db, workspace_id, document, publishing=False)
    stored = _current_version(db, model)
    data = document.model_dump(mode="json")
    stored.document = data
    stored.counts = _counts(document)
    stored.content_digest = _digest(data)
    model.version += 1
    model.updated_by_user_id = actor_user_id
    db.flush()
    add_audit_event(
        db,
        action="semantic_model.draft_updated",
        outcome="success",
        resource_type="semantic_model",
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        resource_id=str(model.id),
        detail=stored.content_digest,
    )
    return _response(db, model)


def publish_semantic_model(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    model_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    version: int,
) -> SemanticModelResponse:
    model = _get_model(db, workspace_id, model_id)
    if model.status != SemanticModelStatus.DRAFT:
        raise SemanticModelServiceError(
            "semantic_model.immutable", "Semantic model is already published"
        )
    if model.version != version:
        raise SemanticModelServiceError(
            "semantic_model.version_conflict", "Semantic model changed; refresh before retrying"
        )
    stored = _current_version(db, model)
    document = SemanticDocument.model_validate(stored.document)
    _validate_references(document)
    if not document.entities or not document.metrics:
        raise SemanticModelServiceError(
            "semantic_model.incomplete", "At least one entity and metric are required"
        )
    _validate_physical_mappings(db, workspace_id, document, publishing=True)
    stored.status = SemanticVersionStatus.PUBLISHED
    stored.published_at = datetime.now(UTC)
    stored.published_by_user_id = actor_user_id
    model.status = SemanticModelStatus.PUBLISHED
    model.active_version_id = stored.id
    model.version += 1
    model.updated_by_user_id = actor_user_id
    db.flush()
    add_audit_event(
        db,
        action="semantic_model.published",
        outcome="success",
        resource_type="semantic_model",
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        resource_id=str(model.id),
        detail=stored.content_digest,
    )
    return _response(db, model)


def create_next_draft(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    model_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    version: int,
) -> SemanticModelResponse:
    model = _get_model(db, workspace_id, model_id)
    if model.status != SemanticModelStatus.PUBLISHED:
        raise SemanticModelServiceError(
            "semantic_model.invalid_state", "Only a published model can start a new draft"
        )
    if model.version != version:
        raise SemanticModelServiceError(
            "semantic_model.version_conflict", "Semantic model changed; refresh before retrying"
        )
    published = _current_version(db, model)
    draft = SemanticModelVersion(
        workspace_id=workspace_id,
        semantic_model_id=model.id,
        revision=published.revision + 1,
        status=SemanticVersionStatus.DRAFT,
        document=published.document,
        counts=published.counts,
        content_digest=published.content_digest,
        created_by_user_id=actor_user_id,
    )
    db.add(draft)
    model.status = SemanticModelStatus.DRAFT
    model.version += 1
    model.updated_by_user_id = actor_user_id
    db.flush()
    add_audit_event(
        db,
        action="semantic_model.draft_created",
        outcome="success",
        resource_type="semantic_model",
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        resource_id=str(model.id),
        detail=f"revision={draft.revision};from={published.content_digest}",
    )
    return _response(db, model)


def _tokens(value: str) -> set[str]:
    return {token for token in re.sub(r"[^a-z0-9]+", "_", value.lower()).split("_") if token}


def mapping_candidates(
    db: Session, *, workspace_id: uuid.UUID, model_id: uuid.UUID, snapshot_id: uuid.UUID
) -> MappingCandidateResponse:
    model = _get_model(db, workspace_id, model_id)
    snapshot = db.scalar(
        select(CatalogSnapshot).where(
            CatalogSnapshot.id == snapshot_id, CatalogSnapshot.workspace_id == workspace_id
        )
    )
    if snapshot is None:
        raise SemanticModelServiceError("catalog.not_found", "Catalog snapshot not found")
    document = SemanticDocument.model_validate(_current_version(db, model).document)
    rows = db.execute(
        select(CatalogColumn, CatalogRelation, CatalogSchema)
        .join(CatalogRelation, CatalogRelation.id == CatalogColumn.relation_id)
        .join(CatalogSchema, CatalogSchema.id == CatalogRelation.schema_id)
        .where(CatalogColumn.snapshot_id == snapshot_id, CatalogColumn.workspace_id == workspace_id)
    ).all()
    candidates: list[MappingCandidate] = []
    unmapped: list[str] = []
    for entity in document.entities:
        for attribute in entity.attributes:
            semantic_ref = f"{entity.key}.{attribute.key}"
            target = _tokens(entity.key) | _tokens(attribute.key)
            ranked: list[tuple[float, CatalogColumn, CatalogRelation, CatalogSchema, str]] = []
            for column, relation, schema in rows:
                column_tokens, relation_tokens = _tokens(column.name), _tokens(relation.name)
                overlap = len(target & (column_tokens | relation_tokens))
                exact = (
                    column.normalized_name == attribute.key or column.name.lower() == attribute.key
                )
                score = min(0.99, (0.72 if exact else 0.25) + overlap * 0.14)
                if score >= 0.39:
                    reason = "列名精确匹配" if exact else "实体与字段词元匹配"
                    ranked.append((score, column, relation, schema, reason))
            if not ranked:
                unmapped.append(semantic_ref)
                continue
            for score, column, relation, schema, reason in sorted(
                ranked, key=lambda item: item[0], reverse=True
            )[:3]:
                candidates.append(
                    MappingCandidate(
                        semantic_attribute=semantic_ref,
                        snapshot_id=snapshot_id,
                        relation_id=relation.id,
                        column_id=column.id,
                        schema_name=schema.name,
                        relation_name=relation.name,
                        column_name=column.name,
                        confidence=round(score, 2),
                        reason=reason,
                    )
                )
    return MappingCandidateResponse(
        snapshot_id=snapshot_id, candidates=candidates, unmapped_attributes=unmapped
    )
