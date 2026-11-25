"""accounts without an email or a password; a session sliding by its own days

Revision ID: auth_0003
Revises: auth_0002
Created: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "auth_0003"
down_revision: str | Sequence[str] | None = "auth_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("auth_user") as b:
        b.alter_column("email", existing_type=sa.String(254), nullable=True)
        b.alter_column("password_hash", existing_type=sa.String(255), nullable=True)
    with op.batch_alter_table("auth_session") as b:
        b.add_column(sa.Column("slide_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("auth_session") as b:
        b.drop_column("slide_days")
    with op.batch_alter_table("auth_user") as b:
        b.alter_column("password_hash", existing_type=sa.String(255), nullable=False)
        b.alter_column("email", existing_type=sa.String(254), nullable=False)
