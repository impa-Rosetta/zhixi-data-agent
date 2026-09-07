"""Allow active data source names to be reused after soft deletion.

Revision ID: 20260906_0006
Revises: 20260905_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0006"
down_revision: str | Sequence[str] | None = "20260905_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_data_source_workspace_name", "data_sources", type_="unique")
    op.create_index(
        "uq_data_source_workspace_name",
        "data_sources",
        ["workspace_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_data_source_workspace_name", table_name="data_sources")
    op.create_unique_constraint(
        "uq_data_source_workspace_name", "data_sources", ["workspace_id", "name"]
    )
