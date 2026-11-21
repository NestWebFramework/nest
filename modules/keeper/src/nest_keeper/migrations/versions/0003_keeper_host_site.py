"""keeper: a site's name on the server, for the host helper (nest-host)

Revision ID: keeper_0003
Revises: keeper_0002
Created: 2026-11-20 23:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "keeper_0003"
down_revision: str | Sequence[str] | None = "keeper_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("keeper_site") as batch:
        batch.add_column(
            sa.Column("host_site", sa.String(length=63), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("keeper_site") as batch:
        batch.drop_column("host_site")
