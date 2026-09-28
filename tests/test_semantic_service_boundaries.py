"""Real ORM candidate ranking, workspace isolation and rejected publication mutations."""

import uuid

import pytest
from sqlalchemy import select

from apps.api.services import semantic_models as service
from packages.platform_core.models import AuditEvent, CatalogColumn, CatalogRelation, CatalogSchema
from packages.semantic_model.models import SemanticModel, SemanticModelStatus, SemanticModelVersion
from packages.shared_contracts.semantic_models import SemanticDocument, SemanticDraftUpdateRequest
from tests.test_query_service_execution import query_db as query_db
from tests.test_semantic_models_api import semantic_document


def seed_model(query_db):
    db, _, _, _, actor, home, _ = query_db
    response = service.create_semantic_model(
        db,
        workspace_id=home,
        actor_user_id=actor,
        name="Synthetic mapping",
        description=None,
        document=SemanticDocument.model_validate(semantic_document()),
    )
    db.commit()
    return response


def columns(query_db, *, foreign=False):
    db, _, source, snapshot, _, home, other = query_db
    workspace = other if foreign else home
    schema = CatalogSchema(
        workspace_id=workspace,
        data_source_id=source.id,
        snapshot_id=snapshot.id,
        stable_key=f"schema-{workspace}",
        name="fixture",
        normalized_name="fixture",
    )
    db.add(schema)
    db.flush()
    result = []
    for index, (table, column) in enumerate(
        [
            ("production_order", "planned_quantity"),
            ("production_order", "quantity"),
            ("production_order", "planned"),
            ("production_order", "production"),
            ("unrelated", "canary_unmatched"),
        ]
    ):
        relation = CatalogRelation(
            workspace_id=workspace,
            data_source_id=source.id,
            snapshot_id=snapshot.id,
            schema_id=schema.id,
            stable_key=f"{workspace}-{index}",
            name=table,
            normalized_name=table,
            relation_type="table",
        )
        db.add(relation)
        db.flush()
        item = CatalogColumn(
            workspace_id=workspace,
            data_source_id=source.id,
            snapshot_id=snapshot.id,
            relation_id=relation.id,
            stable_key=f"{workspace}-{index}-{column}",
            name=column,
            normalized_name=column,
            ordinal_position=1,
            data_type="number",
            native_type="numeric",
            nullable=False,
        )
        db.add(item)
        db.flush()
        result.append(item)
    db.commit()
    return result


def test_candidates_rank_exact_match_limit_three_and_never_expose_foreign_columns(query_db):
    db, _, _, snapshot, _, home, _ = query_db
    model = seed_model(query_db)
    own = columns(query_db)
    foreign = columns(query_db, foreign=True)
    response = service.mapping_candidates(
        db,
        workspace_id=home,
        model_id=model.id,
        snapshot_id=snapshot.id,
    )
    matches = [
        item
        for item in response.candidates
        if item.semantic_attribute == "production_order.planned_quantity"
    ]
    assert len(matches) == 3
    assert matches[0].column_id == own[0].id and matches[0].confidence == 0.99
    assert matches[0].reason == "列名精确匹配"
    assert matches[1].reason == "实体与字段词元匹配"
    assert [item.confidence for item in matches] == sorted(
        [item.confidence for item in matches],
        reverse=True,
    )
    assert not {item.column_id for item in response.candidates} & {item.id for item in foreign}
    assert own[-1].id not in {item.column_id for item in response.candidates}


def test_empty_catalog_reports_unmapped_attributes_without_mutating_model(query_db):
    db, _, _, snapshot, _, home, _ = query_db
    model = seed_model(query_db)
    response = service.mapping_candidates(
        db,
        workspace_id=home,
        model_id=model.id,
        snapshot_id=snapshot.id,
    )
    assert response.candidates == []
    assert response.unmapped_attributes == [
        "production_order.order_id",
        "production_order.planned_quantity",
    ]
    assert db.get(SemanticModel, model.id).version == 1


@pytest.mark.parametrize("target", ["snapshot", "model"])
def test_candidate_foreign_resource_is_not_found(query_db, target):
    db, _, _, snapshot, _, home, other = query_db
    model = seed_model(query_db)
    if target == "snapshot":
        snapshot.workspace_id = other
        db.commit()
    with pytest.raises(service.SemanticModelServiceError) as error:
        service.mapping_candidates(
            db,
            workspace_id=other if target == "model" else home,
            model_id=model.id,
            snapshot_id=snapshot.id,
        )
    assert error.value.code == (
        "catalog.not_found" if target == "snapshot" else "semantic_model.not_found"
    )


@pytest.mark.parametrize("reason", ["unconfirmed", "foreign", "missing", "stale", "empty"])
def test_publication_rejection_preserves_version_pointer_and_audit(query_db, reason):
    db, _, _, snapshot, actor, home, _ = query_db
    model = seed_model(query_db)
    own = columns(query_db)
    document = semantic_document()
    if reason in {"unconfirmed", "foreign", "missing"}:
        column = columns(query_db, foreign=True)[0] if reason == "foreign" else own[0]
        document["mappings"] = [
            {
                "semantic_attribute": "production_order.planned_quantity",
                "snapshot_id": str(snapshot.id),
                "relation_id": str(column.relation_id),
                "column_id": str(uuid.uuid4() if reason == "missing" else column.id),
                "confirmed": reason != "unconfirmed",
                "confidence": 0.99,
                "reason": "synthetic",
            }
        ]
    if reason == "empty":
        document = {"entities": [], "metrics": []}
    stored = db.scalar(
        select(SemanticModelVersion).where(SemanticModelVersion.semantic_model_id == model.id)
    )
    # Synthetic invalid/stale stored state is intentional: exercise publish revalidation.
    stored.document = document
    db.commit()
    before = list(db.scalars(select(AuditEvent.id)))
    with pytest.raises(service.SemanticModelServiceError) as error:
        service.publish_semantic_model(
            db,
            workspace_id=home,
            model_id=model.id,
            actor_user_id=actor,
            version=99 if reason == "stale" else 1,
        )
    assert (
        error.value.code
        == {
            "unconfirmed": "semantic_model.mapping_unconfirmed",
            "foreign": "semantic_model.mapping_not_found",
            "missing": "semantic_model.mapping_not_found",
            "stale": "semantic_model.version_conflict",
            "empty": "semantic_model.incomplete",
        }[reason]
    )
    db.flush()
    persisted = db.get(SemanticModel, model.id)
    assert persisted.version == 1 and persisted.active_version_id is None
    assert persisted.status == SemanticModelStatus.DRAFT
    assert list(db.scalars(select(AuditEvent.id))) == before


def test_confirmed_mapping_publishes_and_is_immutable(query_db):
    db, _, _, snapshot, actor, home, _ = query_db
    model = seed_model(query_db)
    column = columns(query_db)[0]
    document = semantic_document()
    document["mappings"] = [
        {
            "semantic_attribute": "production_order.planned_quantity",
            "snapshot_id": str(snapshot.id),
            "relation_id": str(column.relation_id),
            "column_id": str(column.id),
            "confirmed": True,
            "confidence": 0.99,
            "reason": "synthetic approved",
        }
    ]
    updated = service.update_semantic_draft(
        db,
        workspace_id=home,
        model_id=model.id,
        actor_user_id=actor,
        payload=SemanticDraftUpdateRequest.model_validate({"version": 1, **document}),
    )
    published = service.publish_semantic_model(
        db,
        workspace_id=home,
        model_id=model.id,
        actor_user_id=actor,
        version=updated.version,
    )
    assert published.status == "published" and published.published_version == 1
    assert db.get(SemanticModel, model.id).active_version_id is not None
    with pytest.raises(service.SemanticModelServiceError, match="already published"):
        service.publish_semantic_model(
            db,
            workspace_id=home,
            model_id=model.id,
            actor_user_id=actor,
            version=published.version,
        )


@pytest.mark.parametrize("reference", ["relationship", "dimension", "metric", "mapping"])
def test_invalid_references_cannot_create_model_or_audit(query_db, reference):
    db, _, _, _, actor, home, _ = query_db
    document = semantic_document()
    if reference == "relationship":
        document["relationships"] = [
            {
                "key": "invalid_link",
                "name": "Invalid",
                "from_attribute": "missing.attribute",
                "to_attribute": "production_order.order_id",
                "cardinality": "many_to_one",
            }
        ]
    elif reference == "dimension":
        document["dimensions"][0]["attribute_key"] = "missing_attribute"
    elif reference == "metric":
        document["metrics"][0]["formula"]["attribute"] = "missing.attribute"
    else:
        document["mappings"] = [
            {
                "semantic_attribute": "missing.attribute",
                "snapshot_id": str(uuid.uuid4()),
                "relation_id": str(uuid.uuid4()),
                "column_id": str(uuid.uuid4()),
                "confirmed": True,
                "confidence": 0.99,
                "reason": "synthetic",
            }
        ]
    before = list(db.scalars(select(AuditEvent.id)))
    with pytest.raises(service.SemanticModelServiceError) as error:
        service.create_semantic_model(
            db,
            workspace_id=home,
            actor_user_id=actor,
            name="Invalid",
            description=None,
            document=SemanticDocument.model_validate(document),
        )
    assert error.value.code == "semantic_model.invalid_reference"
    assert list(db.scalars(select(SemanticModel))) == []
    assert list(db.scalars(select(AuditEvent.id))) == before


@pytest.mark.parametrize("action", ["update", "new_draft", "stale_new_draft"])
def test_state_and_optimistic_lock_rejections_have_no_new_revision(query_db, action):
    db, _, _, _, actor, home, _ = query_db
    model = seed_model(query_db)
    if action == "stale_new_draft":
        model = service.publish_semantic_model(
            db,
            workspace_id=home,
            model_id=model.id,
            actor_user_id=actor,
            version=1,
        )
    before = list(db.scalars(select(AuditEvent.id)))
    with pytest.raises(service.SemanticModelServiceError) as error:
        if action == "update":
            service.update_semantic_draft(
                db,
                workspace_id=home,
                model_id=model.id,
                actor_user_id=actor,
                payload=SemanticDraftUpdateRequest.model_validate(
                    {"version": 99, **semantic_document()}
                ),
            )
        else:
            service.create_next_draft(
                db,
                workspace_id=home,
                model_id=model.id,
                actor_user_id=actor,
                version=99,
            )
    assert error.value.code == (
        "semantic_model.invalid_state"
        if action == "new_draft"
        else "semantic_model.version_conflict"
    )
    assert len(list(db.scalars(select(SemanticModelVersion)))) == 1
    assert db.get(SemanticModel, model.id).version == model.version
    assert list(db.scalars(select(AuditEvent.id))) == before
