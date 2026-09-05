"""Add data source security and metadata foundation.

Revision ID: 20260905_0003
Revises: 20260904_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0003"
down_revision: str | Sequence[str] | None = "20260904_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    op.create_table(
        "network_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("allowed_private_cidrs", sa.JSON(), nullable=False),
        sa.Column("allowed_ports", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_network_policy_workspace_name"),
    )
    op.create_index(
        "uq_network_policy_default_workspace",
        "network_policies",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_index("ix_network_policies_workspace_id", "network_policies", ["workspace_id"])

    op.create_table(
        "data_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("network_policy_id", sa.Uuid()),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("host", sa.String(253), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database_name", sa.String(128), nullable=False),
        sa.Column("tls_mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("health_code", sa.String(100)),
        sa.Column("active_snapshot_id", sa.Uuid()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("port >= 1 AND port <= 65535", name="ck_data_source_port"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["network_policy_id"], ["network_policies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_data_source_workspace_name"),
    )
    op.create_index("ix_data_sources_network_policy_id", "data_sources", ["network_policy_id"])
    op.create_index("ix_data_sources_status", "data_sources", ["status"])
    op.create_index("ix_data_sources_workspace_id", "data_sources", ["workspace_id"])

    op.create_table(
        "catalog_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("database_product", sa.String(50), nullable=False),
        sa.Column("database_version", sa.String(100)),
        sa.Column("scan_options", sa.JSON(), nullable=False),
        sa.Column("object_counts", sa.JSON(), nullable=False),
        sa.Column("content_digest", sa.String(64)),
        sa.Column("sampling_enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("data_source_id", "version", name="uq_catalog_snapshot_version"),
    )
    op.create_index(
        "ix_catalog_snapshots_data_source_id", "catalog_snapshots", ["data_source_id"]
    )
    op.create_index("ix_catalog_snapshots_status", "catalog_snapshots", ["status"])
    op.create_index("ix_catalog_snapshots_workspace_id", "catalog_snapshots", ["workspace_id"])
    op.create_foreign_key(
        "fk_data_source_active_snapshot",
        "data_sources",
        "catalog_snapshots",
        ["active_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "data_source_secrets",
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("algorithm", sa.String(30), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("key_version", sa.String(50), nullable=False),
        sa.Column("wrapped_data_key", sa.Text(), nullable=False),
        sa.Column("key_nonce", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("payload_nonce", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
        sa.Column("destroyed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("data_source_id"),
    )

    op.create_table(
        "scan_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("celery_task_id", sa.String(100)),
        sa.Column("phase", sa.String(100)),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("requested_by_user_id", sa.Uuid()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_scan_job_progress"),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_scan_job_idempotency"),
    )
    op.create_index("ix_scan_jobs_data_source_id", "scan_jobs", ["data_source_id"])
    op.create_index("ix_scan_jobs_status", "scan_jobs", ["status"])
    op.create_index("ix_scan_jobs_workspace_id", "scan_jobs", ["workspace_id"])
    op.create_index(
        "uq_scan_job_active_source",
        "scan_jobs",
        ["data_source_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_published_at", "outbox_events", ["published_at"])


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("scan_jobs")
    op.drop_table("data_source_secrets")
    op.drop_constraint("fk_data_source_active_snapshot", "data_sources", type_="foreignkey")
    op.drop_table("catalog_snapshots")
    op.drop_table("data_sources")
    op.drop_table("network_policies")
