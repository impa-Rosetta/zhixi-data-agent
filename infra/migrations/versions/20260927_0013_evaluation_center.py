"""Add workspace scoped evaluation records.

Revision ID: 20260927_0013
Revises: 20260920_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_0013"
down_revision: str | Sequence[str] | None = "20260920_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
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
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("track", sa.String(10), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("suite_version", sa.String(32), nullable=False),
        sa.Column("suite_digest", sa.String(64), nullable=False),
        sa.Column("dataset_id", sa.String(100), nullable=False),
        sa.Column("semantic_version", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("tool_version", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("budget", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(100)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_evaluation_run_workspace_id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_evaluation_run_idempotency"
        ),
        sa.CheckConstraint("track IN ('offline','live')", name="ck_evaluation_run_track"),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','partial','failed','cancelled')",
            name="ck_evaluation_run_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND calls_used >= 0 AND tokens_used >= 0",
            name="ck_evaluation_run_nonnegative",
        ),
    )
    op.create_index(
        "ix_evaluation_run_workspace_created", "evaluation_runs", ["workspace_id", "created_at"]
    )
    op.create_index(
        "ix_evaluation_run_workspace_status", "evaluation_runs", ["workspace_id", "status"]
    )
    op.create_table(
        "evaluation_case_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evaluation_run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(80), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assertion_results", sa.JSON(), nullable=False),
        sa.Column("run_references", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["workspace_id", "evaluation_run_id"],
            ["evaluation_runs.workspace_id", "evaluation_runs.id"],
            ondelete="CASCADE",
            name="fk_evaluation_case_run_workspace",
        ),
        sa.UniqueConstraint("evaluation_run_id", "case_id", name="uq_evaluation_case_run_id"),
        sa.CheckConstraint(
            "status IN ('queued','running','passed','failed','blocked','infra_error')",
            name="ck_evaluation_case_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND duration_ms >= 0", name="ck_evaluation_case_nonnegative"
        ),
    )
    op.create_index(
        "ix_evaluation_case_workspace_run",
        "evaluation_case_results",
        ["workspace_id", "evaluation_run_id"],
    )


def downgrade() -> None:
    op.drop_table("evaluation_case_results")
    op.drop_table("evaluation_runs")
