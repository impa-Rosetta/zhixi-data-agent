"""Workspace-scoped model snapshots, jobs, registry and versions.

Revision ID: 20260929_0015
Revises: 20260927_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0015"
down_revision: str | Sequence[str] | None = "20260927_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_training_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(240), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_model_snapshot_workspace_id"),
        sa.UniqueConstraint("workspace_id", "object_key", name="uq_model_snapshot_object_key"),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 20971520", name="ck_model_snapshot_size"
        ),
    )
    op.create_index(
        "ix_model_snapshot_workspace_created",
        "model_training_snapshots",
        ["workspace_id", "created_at"],
    )
    op.create_table(
        "model_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("training_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("spec_digest", sa.String(64), nullable=False),
        sa.Column("attempt_id", sa.Uuid()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(100)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["workspace_id", "training_snapshot_id"],
            ["model_training_snapshots.workspace_id", "model_training_snapshots.id"],
            ondelete="RESTRICT",
            name="fk_model_job_workspace_snapshot",
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_model_job_workspace_id"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_model_job_idempotency"),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_model_job_status",
        ),
        sa.CheckConstraint("operation IN ('train','predict')", name="ck_model_job_operation"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_model_job_attempt_count"),
    )
    op.create_index(
        "ix_model_job_workspace_status", "model_jobs", ["workspace_id", "status", "created_at"]
    )
    op.create_table(
        "registered_models",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_registered_model_workspace_id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_registered_model_workspace_name"),
    )
    op.create_index(
        "ix_registered_model_workspace_created", "registered_models", ["workspace_id", "created_at"]
    )
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("registered_model_id", sa.Uuid(), nullable=False),
        sa.Column("training_job_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("feature_types", sa.JSON(), nullable=False),
        sa.Column("model_digest", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(240), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "registered_model_id"],
            ["registered_models.workspace_id", "registered_models.id"],
            ondelete="RESTRICT",
            name="fk_model_version_workspace_model",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "training_job_id"],
            ["model_jobs.workspace_id", "model_jobs.id"],
            ondelete="RESTRICT",
            name="fk_model_version_workspace_job",
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_model_version_workspace_id"),
        sa.UniqueConstraint("training_job_id", name="uq_model_version_training_job"),
        sa.UniqueConstraint(
            "registered_model_id", "version_number", name="uq_model_version_number"
        ),
        sa.CheckConstraint("version_number > 0", name="ck_model_version_number"),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 20971520", name="ck_model_version_size"
        ),
    )
    op.create_index(
        "ix_model_version_workspace_model",
        "model_versions",
        ["workspace_id", "registered_model_id"],
    )


def downgrade() -> None:
    op.drop_table("model_versions")
    op.drop_table("registered_models")
    op.drop_table("model_jobs")
    op.drop_table("model_training_snapshots")
