"""Add versioned semantic models.

Revision ID: 20260907_0007
Revises: 20260906_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0007"
down_revision: str | Sequence[str] | None = "20260906_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "semantic_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft", "published", "archived", name="semantic_model_status", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("active_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_semantic_model_workspace_name"),
    )
    op.create_index(
        "ix_semantic_model_workspace_status", "semantic_models", ["workspace_id", "status"]
    )
    op.create_index("ix_semantic_models_workspace_id", "semantic_models", ["workspace_id"])
    op.create_index("ix_semantic_models_status", "semantic_models", ["status"])
    op.create_table(
        "semantic_model_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("semantic_model_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "published", name="semantic_version_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("published_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["semantic_model_id"], ["semantic_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("semantic_model_id", "revision", name="uq_semantic_model_revision"),
    )
    op.create_index(
        "ix_semantic_model_versions_workspace_id", "semantic_model_versions", ["workspace_id"]
    )
    op.create_index(
        "ix_semantic_model_versions_semantic_model_id",
        "semantic_model_versions",
        ["semantic_model_id"],
    )
    op.create_index(
        "ix_semantic_version_workspace_status",
        "semantic_model_versions",
        ["workspace_id", "status"],
    )
    op.create_foreign_key(
        "fk_semantic_model_active_version",
        "semantic_models",
        "semantic_model_versions",
        ["active_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_semantic_model_active_version", "semantic_models", type_="foreignkey")
    op.drop_index("ix_semantic_version_workspace_status", table_name="semantic_model_versions")
    op.drop_index(
        "ix_semantic_model_versions_semantic_model_id", table_name="semantic_model_versions"
    )
    op.drop_index("ix_semantic_model_versions_workspace_id", table_name="semantic_model_versions")
    op.drop_table("semantic_model_versions")
    op.drop_index("ix_semantic_models_status", table_name="semantic_models")
    op.drop_index("ix_semantic_models_workspace_id", table_name="semantic_models")
    op.drop_index("ix_semantic_model_workspace_status", table_name="semantic_models")
    op.drop_table("semantic_models")
