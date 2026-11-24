"""rating

Revision ID: rating_0001
Revises:
Created: 2026-11-24 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "rating_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rating_vote",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("voter", sa.String(length=40), nullable=False),
        sa.Column("print", sa.String(length=32), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("updated", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rating_vote")),
        sa.UniqueConstraint("subject", "voter", name="uq_rating_vote_subject_voter"),
    )
    op.create_index(op.f("ix_rating_vote_subject"), "rating_vote", ["subject"])
    op.create_index(op.f("ix_rating_vote_updated"), "rating_vote", ["updated"])
    op.create_index("ix_rating_vote_subject_print", "rating_vote", ["subject", "print"])
    op.create_table(
        "rating_summary",
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("up", sa.Integer(), nullable=False),
        sa.Column("down", sa.Integer(), nullable=False),
        sa.Column("stars", sa.JSON(), nullable=False),
        sa.Column("closed", sa.Boolean(), nullable=False),
        sa.Column("updated", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("subject", name=op.f("pk_rating_summary")),
    )


def downgrade() -> None:
    op.drop_table("rating_summary")
    op.drop_index("ix_rating_vote_subject_print", table_name="rating_vote")
    op.drop_index(op.f("ix_rating_vote_updated"), table_name="rating_vote")
    op.drop_index(op.f("ix_rating_vote_subject"), table_name="rating_vote")
    op.drop_table("rating_vote")
