import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from packages.connectors.metadata import MetadataDocument


@dataclass(frozen=True)
class CatalogChange:
    change_type: str
    object_type: str
    object_key: str
    severity: str
    before_value: dict[str, Any] | None
    after_value: dict[str, Any] | None


class CatalogValidationError(ValueError):
    pass


def stable_key(*parts: str) -> str:
    return "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


def catalog_objects(document: MetadataDocument) -> dict[str, tuple[str, dict[str, Any]]]:
    objects: dict[str, tuple[str, dict[str, Any]]] = {}
    for schema in document.schemas:
        key = stable_key("schema", schema.name)
        objects[key] = ("schema", asdict(schema))
    for relation in document.relations:
        relation_key = stable_key("relation", relation.schema, relation.name)
        relation_value = {
            "schema": relation.schema,
            "name": relation.name,
            "relation_type": relation.relation_type,
            "comment": relation.comment,
        }
        objects[relation_key] = ("relation", relation_value)
        for column in relation.columns:
            key = stable_key("column", relation.schema, relation.name, column.name)
            objects[key] = ("column", asdict(column))
        for constraint in relation.constraints:
            key = stable_key("constraint", relation.schema, relation.name, constraint.name)
            objects[key] = ("constraint", asdict(constraint))
        for index in relation.indexes:
            key = stable_key("index", relation.schema, relation.name, index.name)
            objects[key] = ("index", asdict(index))
    return objects


def document_digest(document: MetadataDocument) -> str:
    canonical = {
        key: {"object_type": object_type, "value": value}
        for key, (object_type, value) in sorted(catalog_objects(document).items())
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_document(document: MetadataDocument, *, max_objects: int) -> None:
    if not document.database_product or not document.database_version:
        raise CatalogValidationError("Database identity is missing")
    schema_names = [item.name for item in document.schemas]
    if any(not name for name in schema_names) or len(schema_names) != len(set(schema_names)):
        raise CatalogValidationError("Schema names must be non-empty and unique")
    expected = len(schema_names)
    seen_relations: set[tuple[str, str]] = set()
    for relation in document.relations:
        relation_key = (relation.schema, relation.name)
        if (
            relation.schema not in schema_names
            or not relation.name
            or relation_key in seen_relations
        ):
            raise CatalogValidationError("Relation identity is invalid")
        seen_relations.add(relation_key)
        for values in (relation.columns, relation.constraints, relation.indexes):
            names = [item.name for item in values]
            if any(not name for name in names) or len(names) != len(set(names)):
                raise CatalogValidationError("Catalog object names must be non-empty and unique")
        expected += 1 + len(relation.columns) + len(relation.constraints) + len(relation.indexes)
    if expected > max_objects:
        raise CatalogValidationError("Metadata document exceeds the configured object limit")


def diff_documents(
    before: MetadataDocument | None, after: MetadataDocument
) -> tuple[CatalogChange, ...]:
    before_objects = catalog_objects(before) if before is not None else {}
    after_objects = catalog_objects(after)
    changes: list[CatalogChange] = []
    for key in sorted(before_objects.keys() | after_objects.keys()):
        old = before_objects.get(key)
        new = after_objects.get(key)
        if old is None and new is not None:
            changes.append(CatalogChange("added", new[0], key, "info", None, new[1]))
        elif new is None and old is not None:
            changes.append(CatalogChange("removed", old[0], key, "breaking", old[1], None))
        elif old is not None and new is not None and old[1] != new[1]:
            severity = "breaking" if old[0] in {"column", "constraint"} else "warning"
            changes.append(CatalogChange("changed", new[0], key, severity, old[1], new[1]))
    return tuple(changes)
