"""keeper: the servers of host helpers, and a site's copies of its backups at the keeper

Revision ID: keeper_0005
Revises: keeper_0004
Created: 2026-11-27 00:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "keeper_0005"
down_revision: str | Sequence[str] | None = "keeper_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "keeper_server",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=300), nullable=False),
        sa.Column("token", sa.Text(), nullable=False, server_default=""),
        sa.Column("access_id", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("access_secret", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_keeper_server")),
    )
    with op.batch_alter_table("keeper_site") as batch:
        batch.add_column(sa.Column("server_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("backup_folder", sa.String(length=80), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("fetched_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column("fetch_problem", sa.String(length=500), nullable=False, server_default="")
        )
        batch.create_foreign_key(
            "fk_keeper_site_server_id_keeper_server",
            "keeper_server",
            ["server_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("keeper_site") as batch:
        batch.drop_constraint("fk_keeper_site_server_id_keeper_server", type_="foreignkey")
        batch.drop_column("fetch_problem")
        batch.drop_column("fetched_at")
        batch.drop_column("backup_folder")
        batch.drop_column("server_id")
    op.drop_table("keeper_server")
