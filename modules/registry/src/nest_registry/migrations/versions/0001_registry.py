"""packages, releases, files and tokens

Revision ID: registry_0001
Revises:
Created: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "registry_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "registry_package",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("dist", sa.String(160), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("index_only", sa.Boolean(), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_registry_package"),
        sa.UniqueConstraint("name", name="uq_registry_package_name"),
        sa.UniqueConstraint("dist", name="uq_registry_package_dist"),
    )
    op.create_index("ix_registry_package_owner_id", "registry_package", ["owner_id"])
    op.create_table(
        "registry_release",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(60), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("ecosystem", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("nest", sa.String(60), nullable=False),
        sa.Column("requires_python", sa.String(60), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("about", sa.Text(), nullable=False),
        sa.Column("screenshot", sa.String(400), nullable=False),
        sa.Column("uploader_id", sa.Integer(), nullable=False),
        sa.Column("yanked", sa.Boolean(), nullable=False),
        sa.Column("yank_reason", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["registry_package.id"],
            name="fk_registry_release_package_id_registry_package",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_registry_release"),
        sa.UniqueConstraint("package_id", "version", name="uq_registry_release_version"),
    )
    op.create_index("ix_registry_release_package_id", "registry_release", ["package_id"])
    op.create_table(
        "registry_file",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(400), nullable=False),
        sa.Column("signature", sa.String(200), nullable=False),
        sa.Column("signer", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["registry_release.id"],
            name="fk_registry_file_release_id_registry_release",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_registry_file"),
        sa.UniqueConstraint("filename", name="uq_registry_file_filename"),
    )
    op.create_index("ix_registry_file_release_id", "registry_file", ["release_id"])
    op.create_table(
        "registry_token",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("prefix", sa.String(12), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_registry_token"),
        sa.UniqueConstraint("digest", name="uq_registry_token_digest"),
    )
    op.create_index("ix_registry_token_user_id", "registry_token", ["user_id"])
    op.create_table(
        "registry_namespace",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_registry_namespace"),
        sa.UniqueConstraint("name", name="uq_registry_namespace_name"),
    )
    op.create_index("ix_registry_namespace_owner_id", "registry_namespace", ["owner_id"])
    op.create_table(
        "registry_maintainer",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["registry_package.id"],
            name="fk_registry_maintainer_package_id_registry_package",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_registry_maintainer"),
        sa.UniqueConstraint("package_id", "user_id", name="uq_registry_maintainer_user"),
    )
    op.create_index("ix_registry_maintainer_package_id", "registry_maintainer", ["package_id"])
    op.create_index("ix_registry_maintainer_user_id", "registry_maintainer", ["user_id"])
    op.create_table(
        "registry_signing_key",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("public", sa.String(80), nullable=False),
        sa.Column("fingerprint", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_registry_signing_key"),
        sa.UniqueConstraint("user_id", "public", name="uq_registry_signing_key_public"),
    )
    op.create_index("ix_registry_signing_key_user_id", "registry_signing_key", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_registry_signing_key_user_id", table_name="registry_signing_key")
    op.drop_table("registry_signing_key")
    op.drop_index("ix_registry_maintainer_user_id", table_name="registry_maintainer")
    op.drop_index("ix_registry_maintainer_package_id", table_name="registry_maintainer")
    op.drop_table("registry_maintainer")
    op.drop_index("ix_registry_namespace_owner_id", table_name="registry_namespace")
    op.drop_table("registry_namespace")
    op.drop_index("ix_registry_token_user_id", table_name="registry_token")
    op.drop_table("registry_token")
    op.drop_index("ix_registry_file_release_id", table_name="registry_file")
    op.drop_table("registry_file")
    op.drop_index("ix_registry_release_package_id", table_name="registry_release")
    op.drop_table("registry_release")
    op.drop_index("ix_registry_package_owner_id", table_name="registry_package")
    op.drop_table("registry_package")
