"""forum: a board's scope (whose it is: none for a public board)

Revision ID: forum_0002
Revises: forum_0001
Created: 2026-11-21 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "forum_0002"
down_revision: str | Sequence[str] | None = "forum_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("forum_board") as batch:
        batch.add_column(sa.Column("scope", sa.String(length=120), nullable=True))
        batch.create_index("ix_forum_board_scope", ["scope"])


def downgrade() -> None:
    with op.batch_alter_table("forum_board") as batch:
        batch.drop_index("ix_forum_board_scope")
        batch.drop_column("scope")
