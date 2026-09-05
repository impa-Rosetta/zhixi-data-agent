import pytest

from packages.connectors.metadata import (
    MetadataColumn,
    MetadataDocument,
    MetadataRelation,
    MetadataSchema,
)
from packages.platform_core.catalog import (
    CatalogValidationError,
    diff_documents,
    document_digest,
    stable_key,
    validate_document,
)


def document(*, native_type: str = "integer", include_extra: bool = False) -> MetadataDocument:
    columns = [MetadataColumn("id", 1, "integer", native_type, False)]
    if include_extra:
        columns.append(MetadataColumn("order_no", 2, "string", "text", False))
    return MetadataDocument(
        database_product="postgresql",
        database_version="16.4",
        schemas=(MetadataSchema("public"),),
        relations=(
            MetadataRelation(
                schema="public",
                name="orders",
                relation_type="table",
                comment=None,
                columns=tuple(columns),
                constraints=(),
                indexes=(),
            ),
        ),
    )


def test_digest_is_stable_and_ignores_server_version() -> None:
    first = document()
    second = MetadataDocument(
        database_product=first.database_product,
        database_version="16.5",
        schemas=first.schemas,
        relations=first.relations,
    )
    assert document_digest(first) == document_digest(second)


def test_diff_is_deterministic_and_classifies_changes() -> None:
    changes = diff_documents(document(), document(native_type="bigint", include_extra=True))
    assert [(change.change_type, change.object_key, change.severity) for change in changes] == [
        ("changed", "column/public/orders/id", "breaking"),
        ("added", "column/public/orders/order_no", "info"),
    ]


def test_diff_reports_removed_objects() -> None:
    changes = diff_documents(document(include_extra=True), document())
    assert [(item.change_type, item.object_key, item.severity) for item in changes] == [
        ("removed", "column/public/orders/order_no", "breaking")
    ]


def test_catalog_validation_rejects_duplicate_and_orphan_objects() -> None:
    duplicate = MetadataDocument(
        database_product="postgresql",
        database_version="16.4",
        schemas=(MetadataSchema("public"), MetadataSchema("public")),
        relations=(),
    )
    with pytest.raises(CatalogValidationError):
        validate_document(duplicate, max_objects=100)
    orphan = MetadataDocument(
        database_product="postgresql",
        database_version="16.4",
        schemas=(MetadataSchema("public"),),
        relations=(MetadataRelation("missing", "orders", "table", None, (), (), ()),),
    )
    with pytest.raises(CatalogValidationError):
        validate_document(orphan, max_objects=100)
    with pytest.raises(CatalogValidationError):
        validate_document(document(include_extra=True), max_objects=2)


def test_stable_key_escapes_identifier_delimiters_without_collisions() -> None:
    assert stable_key("column", "a/b", "c", "d~e") == "column/a~1b/c/d~0e"
    assert stable_key("column", "a/b", "c", "d") != stable_key("column", "a", "b/c", "d")
