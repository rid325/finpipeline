"""add India regime vectors

Revision ID: e04157ba9c33
Revises: da39b18124b0
Create Date: 2026-10-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e04157ba9c33"
down_revision = "da39b18124b0"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("macro_fingerprints_date_key", "macro_fingerprints", type_="unique")
    op.add_column("macro_fingerprints", sa.Column("method_version", sa.String(40), nullable=False, server_default="legacy-us-v0"))
    op.add_column("macro_fingerprints", sa.Column("raw_features", postgresql.JSONB))
    op.add_column("macro_fingerprints", sa.Column("standardized_features", postgresql.JSONB))
    op.add_column("macro_fingerprints", sa.Column("history_count", sa.Integer))
    op.add_column("macro_fingerprints", sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_unique_constraint("uq_fingerprint_date_method", "macro_fingerprints", ["date", "method_version"])


def downgrade():
    op.drop_constraint("uq_fingerprint_date_method", "macro_fingerprints", type_="unique")
    for column in ("computed_at", "history_count", "standardized_features", "raw_features", "method_version"):
        op.drop_column("macro_fingerprints", column)
    op.create_unique_constraint("macro_fingerprints_date_key", "macro_fingerprints", ["date"])
