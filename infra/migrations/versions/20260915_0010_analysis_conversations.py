"""Add durable multi-turn analysis conversations.

Revision ID: 20260915_0010
Revises: 20260907_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0010"
down_revision: str | Sequence[str] | None = "20260907_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_analysis_run_workspace_id",
        "analysis_runs",
        ["workspace_id", "id"],
    )
    op.create_table(
        "analysis_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("active_turn_id", sa.Uuid(), nullable=True),
        sa.Column("last_turn_sequence", sa.Integer(), nullable=False),
        sa.Column("next_event_sequence", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_analysis_conversation_idempotency",
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_analysis_conversation_workspace_id"
        ),
    )
    op.create_index(
        "ix_analysis_conversation_workspace_updated",
        "analysis_conversations",
        ["workspace_id", "updated_at"],
    )
    op.create_index(
        "ix_analysis_conversations_active_turn_id",
        "analysis_conversations",
        ["active_turn_id"],
    )
    op.create_index(
        "ix_analysis_conversations_created_by_user_id",
        "analysis_conversations",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_analysis_conversations_status", "analysis_conversations", ["status"]
    )
    op.create_index(
        "ix_analysis_conversations_workspace_id",
        "analysis_conversations",
        ["workspace_id"],
    )

    op.create_table(
        "analysis_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("parent_turn_id", sa.Uuid(), nullable=True),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=True),
        sa.Column("relation", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("context_before", sa.JSON(), nullable=False),
        sa.Column("context_after", sa.JSON(), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "conversation_id"],
            ["analysis_conversations.workspace_id", "analysis_conversations.id"],
            name="fk_analysis_turn_conversation_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "analysis_run_id"],
            ["analysis_runs.workspace_id", "analysis_runs.id"],
            name="fk_analysis_turn_run_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_turn_id"], ["analysis_turns.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_run_id", name="uq_analysis_turn_run"),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_analysis_turn_sequence"
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_analysis_turn_workspace_id"),
    )
    op.create_index(
        "ix_analysis_turn_conversation_status",
        "analysis_turns",
        ["conversation_id", "status"],
    )
    for column in (
        "analysis_run_id",
        "conversation_id",
        "parent_turn_id",
        "status",
        "workspace_id",
    ):
        op.create_index(f"ix_analysis_turns_{column}", "analysis_turns", [column])

    op.create_foreign_key(
        "fk_analysis_conversation_active_turn",
        "analysis_conversations",
        "analysis_turns",
        ["active_turn_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("analysis_runs", sa.Column("conversation_id", sa.Uuid(), nullable=True))
    op.add_column("analysis_runs", sa.Column("turn_id", sa.Uuid(), nullable=True))
    op.create_index("ix_analysis_runs_conversation_id", "analysis_runs", ["conversation_id"])
    op.create_index("ix_analysis_runs_turn_id", "analysis_runs", ["turn_id"])
    op.create_unique_constraint("uq_analysis_run_turn", "analysis_runs", ["turn_id"])
    op.create_foreign_key(
        "fk_analysis_run_conversation_workspace",
        "analysis_runs",
        "analysis_conversations",
        ["workspace_id", "conversation_id"],
        ["workspace_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_analysis_run_turn_workspace",
        "analysis_runs",
        "analysis_turns",
        ["workspace_id", "turn_id"],
        ["workspace_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_analysis_run_turn_workspace", "analysis_runs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_analysis_run_conversation_workspace", "analysis_runs", type_="foreignkey"
    )
    op.drop_constraint("uq_analysis_run_turn", "analysis_runs", type_="unique")
    op.drop_index("ix_analysis_runs_turn_id", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_conversation_id", table_name="analysis_runs")
    op.drop_column("analysis_runs", "turn_id")
    op.drop_column("analysis_runs", "conversation_id")

    op.drop_constraint(
        "fk_analysis_conversation_active_turn",
        "analysis_conversations",
        type_="foreignkey",
    )
    op.drop_table("analysis_turns")
    op.drop_table("analysis_conversations")
    op.drop_constraint("uq_analysis_run_workspace_id", "analysis_runs", type_="unique")
