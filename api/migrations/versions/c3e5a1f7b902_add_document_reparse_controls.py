"""add document reparse controls

Revision ID: c3e5a1f7b902
Revises: a7c9f2d4e801
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c3e5a1f7b902"
down_revision: str | None = "a7c9f2d4e801"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "preferred_parser",
            sa.String(length=16),
            nullable=False,
            server_default="auto",
        ),
    )
    op.create_index(
        op.f("ix_documents_content_hash"),
        "documents",
        ["content_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_content_hash"), table_name="documents")
    op.drop_column("documents", "preferred_parser")
    op.drop_column("documents", "content_hash")
