"""Add durable reservations for manual live evaluations.

Revision ID: 20260927_0014
Revises: 20260927_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_0014"
down_revision: str | Sequence[str] | None = "20260927_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("evaluation_runs") as batch:
        batch.add_column(
            sa.Column("calls_reserved", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("tokens_reserved", sa.Integer(), nullable=False, server_default="0")
        )
        batch.drop_constraint("ck_evaluation_run_nonnegative", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_run_nonnegative",
            "attempt_count >= 0 AND calls_used >= 0 AND tokens_used >= 0 "
            "AND calls_reserved >= 0 AND tokens_reserved >= 0",
        )
    op.create_table(
        "evaluation_model_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evaluation_run_id", sa.Uuid(), nullable=False),
        sa.Column("call_key", sa.String(100), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("actual_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "evaluation_run_id"],
            ["evaluation_runs.workspace_id", "evaluation_runs.id"],
            ondelete="CASCADE",
            name="fk_evaluation_call_run_workspace",
        ),
        sa.UniqueConstraint("evaluation_run_id", "call_key", name="uq_evaluation_call_key"),
        sa.CheckConstraint(
            "status IN ('sent','settled','usage_uncertain')", name="ck_evaluation_call_status"
        ),
        sa.CheckConstraint(
            "reserved_tokens > 0 AND (actual_tokens IS NULL OR actual_tokens >= 0)",
            name="ck_evaluation_call_tokens",
        ),
    )
    op.create_index(
        "ix_evaluation_call_workspace_run",
        "evaluation_model_calls",
        ["workspace_id", "evaluation_run_id"],
    )


def downgrade() -> None:
    op.drop_table("evaluation_model_calls")
    with op.batch_alter_table("evaluation_runs") as batch:
        batch.drop_constraint("ck_evaluation_run_nonnegative", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_run_nonnegative",
            "attempt_count >= 0 AND calls_used >= 0 AND tokens_used >= 0",
        )
        batch.drop_column("tokens_reserved")
        batch.drop_column("calls_reserved")
