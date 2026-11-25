"""simpler: no device PIN, no adding a device by digits (the key and passkeys do it)

Revision ID: keys_0004
Revises: keys_0003
Created: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "keys_0004"
down_revision: str | Sequence[str] | None = "keys_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("keys_device_pin")
    op.drop_table("keys_pairing")


def downgrade() -> None:
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
    op.create_table(
        "keys_device_pin",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("pin_hash", sa.String(255), nullable=False),
        sa.Column("tries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_active_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_keys_device_pin"),
    )
