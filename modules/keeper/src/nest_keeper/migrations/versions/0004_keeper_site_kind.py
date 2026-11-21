"""keeper: a site watched through its agent, or as a web address (another program's)

Revision ID: keeper_0004
Revises: keeper_0003
Created: 2026-11-21 00:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "keeper_0004"
down_revision: str | Sequence[str] | None = "keeper_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("keeper_site") as batch:
        batch.add_column(
            sa.Column("kind", sa.String(length=10), nullable=False, server_default="agent")
        )


def downgrade() -> None:
    with op.batch_alter_table("keeper_site") as batch:
        batch.drop_column("kind")
