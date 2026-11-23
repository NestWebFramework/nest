"""push

Revision ID: push_0001
Revises:
Created: 2026-11-23 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "push_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "push_subscription",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("sealed", sa.Text(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("used", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_subscription")),
        sa.UniqueConstraint("key", name=op.f("uq_push_subscription_key")),
    )
    op.create_table(
        "push_job",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("ref", sa.String(length=200), nullable=False),
        sa.Column("due", sa.DateTime(), nullable=False),
        sa.Column("sealed", sa.Text(), nullable=False),
        sa.Column("recheck", sa.String(length=80), nullable=False),
        sa.Column("tries", sa.Integer(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["push_subscription.id"],
            name=op.f("fk_push_job_subscription_id_push_subscription"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_job")),
    )
    op.create_index("ix_push_job_due", "push_job", ["due"])
    op.create_index(op.f("ix_push_job_subscription_id"), "push_job", ["subscription_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_push_job_subscription_id"), table_name="push_job")
    op.drop_index("ix_push_job_due", table_name="push_job")
    op.drop_table("push_job")
    op.drop_table("push_subscription")
