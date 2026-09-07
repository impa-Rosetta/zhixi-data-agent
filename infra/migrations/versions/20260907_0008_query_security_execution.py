"""Add validated queries and immutable execution evidence.

Revision ID: 20260907_0008
Revises: 20260907_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0008"
down_revision: str | Sequence[str] | None = "20260907_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "validated_queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("semantic_model_id", sa.Uuid(), nullable=True),
        sa.Column("semantic_version_id", sa.Uuid(), nullable=True),
        sa.Column("dialect", sa.String(20), nullable=False),
        sa.Column(
            "trust",
            sa.Enum("trusted", "exploratory", name="query_trust", native_enum=False),
            nullable=False,
        ),
        sa.Column("protocol", sa.JSON(), nullable=False),
        sa.Column("sql_text", sa.Text(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("safety_report", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("row_limit", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["catalog_snapshots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["semantic_model_id"], ["semantic_models.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["semantic_version_id"], ["semantic_model_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_validated_queries_workspace_id", ["workspace_id"]),
        ("ix_validated_queries_data_source_id", ["data_source_id"]),
        ("ix_validated_queries_snapshot_id", ["snapshot_id"]),
        ("ix_validated_queries_semantic_model_id", ["semantic_model_id"]),
        ("ix_validated_queries_semantic_version_id", ["semantic_version_id"]),
        ("ix_validated_queries_trust", ["trust"]),
        ("ix_validated_queries_digest", ["digest"]),
        ("ix_validated_queries_expires_at", ["expires_at"]),
        ("ix_validated_query_workspace_created", ["workspace_id", "created_at"]),
    ):
        op.create_index(name, "validated_queries", columns)
    op.create_table(
        "query_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("validated_query_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "succeeded", "failed", "cancelled", name="query_execution_status", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column("columns", sa.JSON(), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("result_digest", sa.String(64), nullable=True),
        sa.Column("evidence_digest", sa.String(64), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["validated_query_id"], ["validated_queries.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_query_executions_workspace_id", ["workspace_id"]),
        ("ix_query_executions_validated_query_id", ["validated_query_id"]),
        ("ix_query_executions_status", ["status"]),
        ("ix_query_executions_evidence_digest", ["evidence_digest"]),
        ("ix_query_execution_workspace_started", ["workspace_id", "started_at"]),
    ):
        op.create_index(name, "query_executions", columns)


def downgrade() -> None:
    op.drop_table("query_executions")
    op.drop_table("validated_queries")
