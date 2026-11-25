"""passkeys, and the WebAuthn challenges under way

Revision ID: keys_0002
Revises: keys_0001
Created: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "keys_0002"
down_revision: str | Sequence[str] | None = "keys_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "keys_passkey",
        sa.Column("id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transports", sa.String(120), nullable=False, server_default=""),
        sa.Column("name", sa.String(120), nullable=False, server_default=""),
        sa.Column("synced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_keys_passkey"),
    )
    op.create_index("ix_keys_passkey_user_id", "keys_passkey", ["user_id"])
    op.create_table(
        "keys_challenge",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("challenge", sa.LargeBinary(), nullable=False),
        sa.Column("purpose", sa.String(10), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_keys_challenge"),
    )


def downgrade() -> None:
    op.drop_table("keys_challenge")
    op.drop_table("keys_passkey")
