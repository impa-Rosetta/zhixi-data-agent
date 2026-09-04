"""Create platform bootstrap metadata.

Revision ID: 20260904_0001
Revises:
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260904_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_metadata",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute(
        sa.text("INSERT INTO platform_metadata (key, value) VALUES ('schema_version', '0.1.0')")
    )


def downgrade() -> None:
    op.drop_table("platform_metadata")

