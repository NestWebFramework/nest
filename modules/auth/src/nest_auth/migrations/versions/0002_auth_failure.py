"""failed sign-ins, shared by every worker

Revision ID: auth_0002
Revises: auth_0001
Created: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "auth_0002"
down_revision: str | Sequence[str] | None = "auth_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_failure",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_failure"),
    )
    op.create_index("ix_auth_failure_key_at", "auth_failure", ["key", "at"])
    op.create_index("ix_auth_failure_at", "auth_failure", ["at"])


def downgrade() -> None:
    op.drop_index("ix_auth_failure_at", table_name="auth_failure")
    op.drop_index("ix_auth_failure_key_at", table_name="auth_failure")
    op.drop_table("auth_failure")
