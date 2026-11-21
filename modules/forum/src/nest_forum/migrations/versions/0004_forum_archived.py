"""forum: boards and topics put away (archived)

Revision ID: forum_0004
Revises: forum_0003
Created: 2026-11-21 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "forum_0004"
down_revision: str | Sequence[str] | None = "forum_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("forum_board", "forum_topic"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false())
            )


def downgrade() -> None:
    for table in ("forum_board", "forum_topic"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("archived")
