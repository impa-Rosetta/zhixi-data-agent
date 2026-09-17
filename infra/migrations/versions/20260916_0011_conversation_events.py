"""Add replayable conversation events.

Revision ID: 20260916_0011
Revises: 20260915_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0011"
down_revision: str | Sequence[str] | None = "20260915_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_conversation_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("run_event_sequence", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "conversation_id"],
            ["analysis_conversations.workspace_id", "analysis_conversations.id"],
            name="fk_analysis_conversation_event_conversation_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["turn_id"], ["analysis_turns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_analysis_conversation_event_sequence",
        ),
    )
    op.create_index(
        "ix_analysis_conversation_event_replay",
        "analysis_conversation_events",
        ["conversation_id", "sequence"],
    )
    for column in ("workspace_id", "conversation_id", "turn_id", "run_id", "event_type"):
        op.create_index(
            f"ix_analysis_conversation_events_{column}",
            "analysis_conversation_events",
            [column],
        )


def downgrade() -> None:
    op.drop_table("analysis_conversation_events")
