"""Add trusted analysis reports and generated files.

Revision ID: 20260920_0012
Revises: 20260916_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260920_0012"
down_revision: str | Sequence[str] | None = "20260916_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("template_key", sa.String(100), nullable=False),
        sa.Column("template_version", sa.String(32), nullable=False),
        sa.Column("renderer_version", sa.String(32), nullable=False),
        sa.Column("report_spec", sa.JSON(), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "conversation_id"],
            ["analysis_conversations.workspace_id", "analysis_conversations.id"],
            name="fk_analysis_report_conversation_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_analysis_report_idempotency"
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_analysis_report_workspace_id"),
    )
    op.create_index(
        "ix_analysis_report_workspace_created",
        "analysis_reports",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_analysis_report_workspace_status",
        "analysis_reports",
        ["workspace_id", "status"],
    )
    for column in (
        "workspace_id",
        "conversation_id",
        "created_by_user_id",
        "status",
        "source_digest",
        "content_digest",
        "expires_at",
    ):
        op.create_index(f"ix_analysis_reports_{column}", "analysis_reports", [column])

    op.create_table(
        "analysis_report_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "report_id"],
            ["analysis_reports.workspace_id", "analysis_reports.id"],
            name="fk_analysis_report_file_report_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "format", name="uq_analysis_report_file_format"),
    )
    op.create_index(
        "ix_analysis_report_file_workspace_report",
        "analysis_report_files",
        ["workspace_id", "report_id"],
    )
    for column in ("workspace_id", "report_id", "format", "sha256_digest", "expires_at"):
        op.create_index(
            f"ix_analysis_report_files_{column}", "analysis_report_files", [column]
        )


def downgrade() -> None:
    op.drop_table("analysis_report_files")
    op.drop_table("analysis_reports")
