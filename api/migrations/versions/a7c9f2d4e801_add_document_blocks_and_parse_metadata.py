"""add document blocks and parse metadata

Revision ID: a7c9f2d4e801
Revises: 6727223d45f9
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a7c9f2d4e801"
down_revision: str | None = "6727223d45f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("parser_name", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("parser_version", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("parse_status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "parse_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_documents_parse_status"),
        "documents",
        ["parse_status"],
        unique=False,
    )

    op.create_table(
        "document_blocks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column(
            "heading_path",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "extra_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "block_order",
            name="uq_document_blocks_document_order",
        ),
    )
    op.create_index(
        op.f("ix_document_blocks_block_type"),
        "document_blocks",
        ["block_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_blocks_document_id"),
        "document_blocks",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_document_blocks_document_id"),
        table_name="document_blocks",
    )
    op.drop_index(
        op.f("ix_document_blocks_block_type"),
        table_name="document_blocks",
    )
    op.drop_table("document_blocks")
    op.drop_index(op.f("ix_documents_parse_status"), table_name="documents")
    op.drop_column("documents", "parsed_at")
    op.drop_column("documents", "parse_summary")
    op.drop_column("documents", "parse_status")
    op.drop_column("documents", "parser_version")
    op.drop_column("documents", "parser_name")
