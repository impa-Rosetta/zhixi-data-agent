from typing import Any

import pytest

from packages.connectors.metadata import MetadataDocument
from packages.connectors.mysql import MySQLConnector
from packages.connectors.postgresql import PostgreSQLConnector
from packages.platform_core.catalog import validate_document
from packages.platform_core.catalog_store import object_counts


def _signature(document: MetadataDocument) -> tuple[object, ...]:
    relation = document.relations[0]
    return (
        relation.name,
        relation.relation_type,
        tuple((column.name, column.data_type, column.nullable) for column in relation.columns),
        tuple(
            (constraint.constraint_type, constraint.columns) for constraint in relation.constraints
        ),
        tuple((index.unique, index.method, index.columns) for index in relation.indexes),
    )


@pytest.fixture
def equivalent_documents() -> tuple[MetadataDocument, MetadataDocument]:
    postgres = PostgreSQLConnector._document(
        "16.4",
        ("public",),
        {"public": None},
        [("public", "orders", "table", "Orders")],
        [
            ("public", "orders", "id", 1, "bigint", "N", False, None, None),
            ("public", "orders", "code", 2, "text", "S", False, None, None),
        ],
        [("public", "orders", "orders_pkey", "primary_key", ["id"], None, None, [])],
        [("public", "orders", "orders_pkey", True, "btree", ["id"], None)],
    )
    mysql_rows: dict[str, list[tuple[Any, ...]]] = {
        "schemas": [("factory_demo", None)],
        "relations": [("factory_demo", "orders", "table", "Orders")],
        "columns": [
            ("factory_demo", "orders", "id", 1, "bigint", "bigint", "NO", None, None),
            ("factory_demo", "orders", "code", 2, "text", "text", "NO", None, None),
        ],
        "constraints": [
            (
                "factory_demo",
                "orders",
                "PRIMARY",
                "primary_key",
                "id",
                1,
                None,
                None,
                None,
            )
        ],
        "indexes": [("factory_demo", "orders", "PRIMARY", True, "BTREE", 1, "id", None)],
    }
    mysql = MySQLConnector._document(
        "8.4.11",
        mysql_rows["schemas"],
        mysql_rows["relations"],
        mysql_rows["columns"],
        mysql_rows["constraints"],
        mysql_rows["indexes"],
    )
    return postgres, mysql


def test_database_connectors_emit_the_same_portable_contract(
    equivalent_documents: tuple[MetadataDocument, MetadataDocument],
) -> None:
    postgres, mysql = equivalent_documents
    validate_document(postgres, max_objects=100)
    validate_document(mysql, max_objects=100)
    assert _signature(postgres) == _signature(mysql)
    assert object_counts(postgres) == object_counts(mysql)
