"""Add sampling, profiling, scheduling, and job recovery controls.

Revision ID: 20260905_0005
Revises: 20260905_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0005"
down_revision: str | Sequence[str] | None = "20260905_0004"
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
    op.add_column("scan_jobs", sa.Column("parent_job_id", sa.Uuid()))
    op.add_column("scan_jobs", sa.Column("retry_of_job_id", sa.Uuid()))
    op.add_column("scan_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column("scan_jobs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_scan_job_parent",
        "scan_jobs",
        "scan_jobs",
        ["parent_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_scan_job_retry_of",
        "scan_jobs",
        "scan_jobs",
        ["retry_of_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_scan_jobs_parent_job_id", "scan_jobs", ["parent_job_id"])
    op.create_index("ix_scan_jobs_retry_of_job_id", "scan_jobs", ["retry_of_job_id"])
    op.create_index("ix_scan_jobs_heartbeat_at", "scan_jobs", ["heartbeat_at"])

    op.add_column(
        "catalog_snapshots",
        sa.Column("profiling_status", sa.String(32), server_default="disabled", nullable=False),
    )
    op.add_column("catalog_snapshots", sa.Column("profiling_error_code", sa.String(100)))
    op.add_column(
        "catalog_snapshots",
        sa.Column(
            "profiling_options", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False
        ),
    )
    op.add_column(
        "catalog_snapshots",
        sa.Column(
            "profile_counts", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False
        ),
    )
    op.add_column(
        "catalog_snapshots", sa.Column("profiling_started_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "catalog_snapshots", sa.Column("profiling_finished_at", sa.DateTime(timezone=True))
    )
    op.create_index(
        "ix_catalog_snapshots_profiling_status", "catalog_snapshots", ["profiling_status"]
    )

    op.create_table(
        "sampling_policies",
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("schema_allowlist", sa.JSON(), nullable=False),
        sa.Column("table_allowlist", sa.JSON(), nullable=False),
        sa.Column("max_rows_per_table", sa.Integer(), nullable=False),
        sa.Column("max_values_per_column", sa.Integer(), nullable=False),
        sa.Column("max_value_chars", sa.Integer(), nullable=False),
        sa.Column("max_bytes_per_table", sa.Integer(), nullable=False),
        sa.Column("max_bytes_per_job", sa.Integer(), nullable=False),
        sa.Column("statement_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "max_rows_per_table >= 1 AND max_rows_per_table <= 20",
            name="ck_sampling_rows_per_table",
        ),
        sa.CheckConstraint(
            "max_values_per_column >= 1 AND max_values_per_column <= 20",
            name="ck_sampling_values_per_column",
        ),
        sa.CheckConstraint(
            "max_value_chars >= 16 AND max_value_chars <= 256",
            name="ck_sampling_value_chars",
        ),
        sa.CheckConstraint("max_bytes_per_table >= 1024", name="ck_sampling_table_bytes"),
        sa.CheckConstraint(
            "max_bytes_per_job >= max_bytes_per_table", name="ck_sampling_job_bytes"
        ),
        sa.CheckConstraint(
            "statement_timeout_seconds >= 1 AND statement_timeout_seconds <= 10",
            name="ck_sampling_statement_timeout",
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("data_source_id"),
    )
    op.create_index("ix_sampling_policies_workspace_id", "sampling_policies", ["workspace_id"])

    op.create_table(
        "scan_schedules",
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("local_time", sa.Time(), nullable=False),
        sa.Column("day_of_week", sa.Integer()),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "day_of_week IS NULL OR (day_of_week >= 0 AND day_of_week <= 6)",
            name="ck_scan_schedule_day",
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("data_source_id"),
    )
    op.create_index("ix_scan_schedules_workspace_id", "scan_schedules", ["workspace_id"])
    op.create_index("ix_scan_schedules_next_run_at", "scan_schedules", ["next_run_at"])

    op.create_table(
        "catalog_column_profiles",
        *_scope_columns(),
        sa.Column("column_id", sa.Uuid(), nullable=False),
        sa.Column("sample_row_count", sa.Integer(), nullable=False),
        sa.Column("non_null_count", sa.Integer(), nullable=False),
        sa.Column("estimated_row_count", sa.Integer()),
        sa.Column("sample_null_rate", sa.Float()),
        sa.Column("sampled_distinct_count", sa.Integer()),
        sa.Column("minimum_value", sa.Text()),
        sa.Column("maximum_value", sa.Text()),
        sa.Column("minimum_length", sa.Integer()),
        sa.Column("maximum_length", sa.Integer()),
        sa.Column("average_length", sa.Float()),
        sa.Column("sensitivity_type", sa.String(50)),
        sa.Column("sensitivity_confidence", sa.Float(), nullable=False),
        sa.Column("sensitivity_reasons", sa.JSON(), nullable=False),
        sa.Column("metric_sources", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        *_scope_constraints(),
        sa.ForeignKeyConstraint(["column_id"], ["catalog_columns.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "sensitivity_confidence >= 0 AND sensitivity_confidence <= 1",
            name="ck_profile_sensitivity_confidence",
        ),
        sa.CheckConstraint(
            "sample_null_rate IS NULL OR (sample_null_rate >= 0 AND sample_null_rate <= 1)",
            name="ck_profile_null_rate",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "column_id", name="uq_catalog_column_profile"),
    )
    _scope_indexes("catalog_column_profiles")
    op.create_index(
        "ix_catalog_column_profiles_column_id", "catalog_column_profiles", ["column_id"]
    )
    op.create_index(
        "ix_catalog_column_profiles_sensitivity_type",
        "catalog_column_profiles",
        ["sensitivity_type"],
    )

    op.create_table(
        "catalog_samples",
        *_scope_columns(),
        sa.Column("column_profile_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("masked_value", sa.String(256), nullable=False),
        sa.Column("value_type", sa.String(32), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        *_scope_constraints(),
        sa.ForeignKeyConstraint(
            ["column_profile_id"], ["catalog_column_profiles.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("ordinal >= 1 AND ordinal <= 20", name="ck_catalog_sample_ordinal"),
        sa.CheckConstraint("byte_count >= 0", name="ck_catalog_sample_bytes"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("column_profile_id", "ordinal", name="uq_catalog_sample_ordinal"),
    )
    _scope_indexes("catalog_samples")
    op.create_index(
        "ix_catalog_samples_column_profile_id", "catalog_samples", ["column_profile_id"]
    )


def downgrade() -> None:
    op.drop_table("catalog_samples")
    op.drop_table("catalog_column_profiles")
    op.drop_table("scan_schedules")
    op.drop_table("sampling_policies")

    op.drop_index("ix_catalog_snapshots_profiling_status", table_name="catalog_snapshots")
    for column in (
        "profiling_finished_at",
        "profiling_started_at",
        "profile_counts",
        "profiling_options",
        "profiling_error_code",
        "profiling_status",
    ):
        op.drop_column("catalog_snapshots", column)

    op.drop_index("ix_scan_jobs_heartbeat_at", table_name="scan_jobs")
    op.drop_index("ix_scan_jobs_retry_of_job_id", table_name="scan_jobs")
    op.drop_index("ix_scan_jobs_parent_job_id", table_name="scan_jobs")
    op.drop_constraint("fk_scan_job_retry_of", "scan_jobs", type_="foreignkey")
    op.drop_constraint("fk_scan_job_parent", "scan_jobs", type_="foreignkey")
    for column in ("cancel_requested_at", "heartbeat_at", "retry_of_job_id", "parent_job_id"):
        op.drop_column("scan_jobs", column)
