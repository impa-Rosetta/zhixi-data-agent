from dataclasses import dataclass


@dataclass(frozen=True)
class MetadataColumn:
    name: str
    ordinal_position: int
    data_type: str
    native_type: str
    nullable: bool
    default_expression: str | None = None
    comment: str | None = None


@dataclass(frozen=True)
class MetadataConstraint:
    name: str
    constraint_type: str
    columns: tuple[str, ...]
    referenced_schema: str | None = None
    referenced_relation: str | None = None
    referenced_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetadataIndex:
    name: str
    columns: tuple[str, ...]
    unique: bool
    method: str | None = None
    predicate: str | None = None


@dataclass(frozen=True)
class MetadataRelation:
    schema: str
    name: str
    relation_type: str
    comment: str | None
    columns: tuple[MetadataColumn, ...]
    constraints: tuple[MetadataConstraint, ...]
    indexes: tuple[MetadataIndex, ...]


@dataclass(frozen=True)
class MetadataSchema:
    name: str
    comment: str | None = None


@dataclass(frozen=True)
class MetadataDocument:
    database_product: str
    database_version: str
    schemas: tuple[MetadataSchema, ...]
    relations: tuple[MetadataRelation, ...]


@dataclass(frozen=True)
class MetadataScanOptions:
    schemas: tuple[str, ...] = ()
    max_objects: int = 10_000
