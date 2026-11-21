"""scheduler: each job's state, its runs, the lease

Revision ID: scheduler_0001
Revises:
Created: 2026-11-21 00:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "scheduler_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduler_job",
        sa.Column("key", sa.String(length=130), nullable=False),
        sa.Column("next_at", sa.DateTime(), nullable=True),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("run_now", sa.Boolean(), nullable=False),
        sa.Column("running_since", sa.DateTime(), nullable=True),
        sa.Column("last_at", sa.DateTime(), nullable=True),
        sa.Column("last_ok", sa.Boolean(), nullable=True),
        sa.Column("last_ms", sa.Integer(), nullable=True),
        sa.Column("last_result", sa.Text(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_scheduler_job")),
    )
    op.create_table(
        "scheduler_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=130), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=True),
        sa.Column("ms", sa.Integer(), nullable=True),
        sa.Column("why", sa.String(length=20), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduler_run")),
    )
    op.create_index("ix_scheduler_run_key_started", "scheduler_run", ["key", "started_at"])
    op.create_table(
        "scheduler_lease",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("holder", sa.String(length=120), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_scheduler_lease")),
    )


def downgrade() -> None:
    op.drop_table("scheduler_lease")
    op.drop_index("ix_scheduler_run_key_started", table_name="scheduler_run")
    op.drop_table("scheduler_run")
    op.drop_table("scheduler_job")
