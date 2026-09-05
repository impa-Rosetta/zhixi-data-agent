"""Add versioned normalized metadata catalog.

Revision ID: 20260905_0004
Revises: 20260905_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0004"
down_revision: str | Sequence[str] | None = "20260905_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _scope_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
    )


def _scope_constraints() -> tuple[sa.ForeignKeyConstraint, ...]:
    return (
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["catalog_snapshots.id"], ondelete="CASCADE"),
    )


def _scope_indexes(table: str) -> None:
    for column in ("workspace_id", "data_source_id", "snapshot_id"):
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.add_column(
        "scan_jobs",
        sa.Column("parameters", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )
    op.add_column("scan_jobs", sa.Column("snapshot_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_scan_job_snapshot",
        "scan_jobs",
        "catalog_snapshots",
        ["snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_scan_jobs_snapshot_id", "scan_jobs", ["snapshot_id"])

    op.create_table(
        "catalog_schemas",
        *_scope_columns(),
        sa.Column("stable_key", sa.String(700), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("normalized_name", sa.String(128), nullable=False),
        sa.Column("comment", sa.Text()),
        *_scope_constraints(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "stable_key", name="uq_catalog_schema_key"),
    )
    _scope_indexes("catalog_schemas")
    op.create_index("ix_catalog_schemas_normalized_name", "catalog_schemas", ["normalized_name"])

    op.create_table(
        "catalog_relations",
        *_scope_columns(),
        sa.Column("schema_id", sa.Uuid(), nullable=False),
        sa.Column("stable_key", sa.String(700), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("normalized_name", sa.String(128), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text()),
        *_scope_constraints(),
        sa.ForeignKeyConstraint(["schema_id"], ["catalog_schemas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "stable_key", name="uq_catalog_relation_key"),
    )
    _scope_indexes("catalog_relations")
    op.create_index("ix_catalog_relations_schema_id", "catalog_relations", ["schema_id"])
    op.create_index(
        "ix_catalog_relations_normalized_name", "catalog_relations", ["normalized_name"]
    )

    op.create_table(
        "catalog_columns",
        *_scope_columns(),
        sa.Column("relation_id", sa.Uuid(), nullable=False),
        sa.Column("stable_key", sa.String(700), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("normalized_name", sa.String(128), nullable=False),
        sa.Column("ordinal_position", sa.Integer(), nullable=False),
        sa.Column("data_type", sa.String(64), nullable=False),
        sa.Column("native_type", sa.String(256), nullable=False),
        sa.Column("nullable", sa.Boolean(), nullable=False),
        sa.Column("default_expression", sa.Text()),
        sa.Column("comment", sa.Text()),
        *_scope_constraints(),
        sa.ForeignKeyConstraint(["relation_id"], ["catalog_relations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "stable_key", name="uq_catalog_column_key"),
    )
    _scope_indexes("catalog_columns")
    op.create_index("ix_catalog_columns_relation_id", "catalog_columns", ["relation_id"])
    op.create_index("ix_catalog_columns_normalized_name", "catalog_columns", ["normalized_name"])
    op.create_index("ix_catalog_columns_data_type", "catalog_columns", ["data_type"])

    op.create_table(
        "catalog_constraints",
        *_scope_columns(),
        sa.Column("relation_id", sa.Uuid(), nullable=False),
        sa.Column("stable_key", sa.String(700), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("constraint_type", sa.String(32), nullable=False),
        sa.Column("column_names", sa.JSON(), nullable=False),
        sa.Column("referenced_schema", sa.String(128)),
        sa.Column("referenced_relation", sa.String(128)),
        sa.Column("referenced_columns", sa.JSON(), nullable=False),
        *_scope_constraints(),
        sa.ForeignKeyConstraint(["relation_id"], ["catalog_relations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "stable_key", name="uq_catalog_constraint_key"),
    )
    _scope_indexes("catalog_constraints")
    op.create_index(
        "ix_catalog_constraints_relation_id", "catalog_constraints", ["relation_id"]
    )
    op.create_index(
        "ix_catalog_constraints_constraint_type", "catalog_constraints", ["constraint_type"]
    )

    op.create_table(
        "catalog_indexes",
        *_scope_columns(),
        sa.Column("relation_id", sa.Uuid(), nullable=False),
        sa.Column("stable_key", sa.String(700), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("column_names", sa.JSON(), nullable=False),
        sa.Column("is_unique", sa.Boolean(), nullable=False),
        sa.Column("method", sa.String(64)),
        sa.Column("predicate", sa.Text()),
        *_scope_constraints(),
        sa.ForeignKeyConstraint(["relation_id"], ["catalog_relations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "stable_key", name="uq_catalog_index_key"),
    )
    _scope_indexes("catalog_indexes")
    op.create_index("ix_catalog_indexes_relation_id", "catalog_indexes", ["relation_id"])

    op.create_table(
        "catalog_diffs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("from_snapshot_id", sa.Uuid()),
        sa.Column("to_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("change_type", sa.String(32), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_key", sa.String(700), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("before_value", sa.JSON()),
        sa.Column("after_value", sa.JSON()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["from_snapshot_id"], ["catalog_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["to_snapshot_id"], ["catalog_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_snapshot_id",
            "to_snapshot_id",
            "object_key",
            "change_type",
            name="uq_catalog_diff_change",
        ),
    )
    for column in (
        "workspace_id",
        "data_source_id",
        "from_snapshot_id",
        "to_snapshot_id",
        "change_type",
        "object_type",
        "severity",
    ):
        op.create_index(f"ix_catalog_diffs_{column}", "catalog_diffs", [column])


def downgrade() -> None:
    op.drop_table("catalog_diffs")
    op.drop_table("catalog_indexes")
    op.drop_table("catalog_constraints")
    op.drop_table("catalog_columns")
    op.drop_table("catalog_relations")
    op.drop_table("catalog_schemas")
    op.drop_index("ix_scan_jobs_snapshot_id", table_name="scan_jobs")
    op.drop_constraint("fk_scan_job_snapshot", "scan_jobs", type_="foreignkey")
    op.drop_column("scan_jobs", "snapshot_id")
    op.drop_column("scan_jobs", "parameters")
