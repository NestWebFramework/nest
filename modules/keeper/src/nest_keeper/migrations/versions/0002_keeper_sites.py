"""keeper: the sites it watches, their checks, the actions asked of them

Revision ID: keeper_0002
Revises: keeper_0001
Created: 2026-11-20 16:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "keeper_0002"
down_revision: str | Sequence[str] | None = "keeper_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "keeper_site",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=300), nullable=False),
        sa.Column("agent", sa.String(length=300), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("up", sa.Boolean(), nullable=True),
        sa.Column("since", sa.DateTime(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("problem", sa.String(length=500), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_keeper_site")),
    )
    op.create_table(
        "keeper_check",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("up", sa.Boolean(), nullable=False),
        sa.Column("reached", sa.Boolean(), nullable=False),
        sa.Column("ms", sa.Integer(), nullable=True),
        sa.Column("code", sa.Integer(), nullable=True),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("problem", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["keeper_site.id"],
            name=op.f("fk_keeper_check_site_id_keeper_site"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_keeper_check")),
    )
    op.create_index("ix_keeper_check_site_at", "keeper_check", ["site_id", "at"])
    op.create_table(
        "keeper_action",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("who", sa.String(length=200), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["keeper_site.id"],
            name=op.f("fk_keeper_action_site_id_keeper_site"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_keeper_action")),
    )


def downgrade() -> None:
    op.drop_table("keeper_action")
    op.drop_index("ix_keeper_check_site_at", table_name="keeper_check")
    op.drop_table("keeper_check")
    op.drop_table("keeper_site")
