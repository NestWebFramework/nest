"""the account's key, devices being added

Revision ID: keys_0001
Revises:
Created: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "keys_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "keys_account_key",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("saved", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name="pk_keys_account_key"),
    )
    op.create_index("ix_keys_account_key_user_id", "keys_account_key", ["user_id"], unique=True)
    op.create_table(
        "keys_pairing",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("link", sa.String(64), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("tries", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name="pk_keys_pairing"),
        sa.UniqueConstraint("link", name="uq_keys_pairing_link"),
    )
    op.create_index("ix_keys_pairing_user_id", "keys_pairing", ["user_id"])
    op.create_index("ix_keys_pairing_code", "keys_pairing", ["code"])


def downgrade() -> None:
    op.drop_table("keys_pairing")
    op.drop_table("keys_account_key")
