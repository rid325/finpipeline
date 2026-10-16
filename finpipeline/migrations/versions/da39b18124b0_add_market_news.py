"""add market news

Revision ID: da39b18124b0
Revises: c4f018c2ae12
Create Date: 2026-10-17
"""
from alembic import op
import sqlalchemy as sa

revision = "da39b18124b0"
down_revision = "c4f018c2ae12"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "news_articles",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("snippet", sa.Text),
    )
    op.create_index("ix_news_published", "news_articles", ["published_at"])
    op.create_index("ix_news_source_published", "news_articles", ["source", "published_at"])
    op.create_table(
        "news_tags",
        sa.Column("article_id", sa.BigInteger, sa.ForeignKey("news_articles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_type", sa.String(16), primary_key=True),
        sa.Column("tag", sa.String(64), primary_key=True),
    )
    op.create_index("ix_news_tags_lookup", "news_tags", ["tag_type", "tag"])


def downgrade():
    op.drop_index("ix_news_tags_lookup", table_name="news_tags")
    op.drop_table("news_tags")
    op.drop_index("ix_news_source_published", table_name="news_articles")
    op.drop_index("ix_news_published", table_name="news_articles")
    op.drop_table("news_articles")
