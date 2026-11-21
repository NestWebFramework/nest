"""forum: boards in boards (a board's parent)

Revision ID: forum_0003
Revises: forum_0002
Created: 2026-11-21 19:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "forum_0003"
down_revision: str | Sequence[str] | None = "forum_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("forum_board") as batch:
        batch.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch.create_index("ix_forum_board_parent_id", ["parent_id"])
        batch.create_foreign_key(
            "fk_forum_board_parent_id_forum_board",
            "forum_board",
            ["parent_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("forum_board") as batch:
        batch.drop_constraint("fk_forum_board_parent_id_forum_board", type_="foreignkey")
        batch.drop_index("ix_forum_board_parent_id")
        batch.drop_column("parent_id")
