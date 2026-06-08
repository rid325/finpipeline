"""add macro fingerprints table

Revision ID: f03d946d7afa
Revises: 72e85f336b2c
Create Date: 2026-06-08

"""
from alembic import op
import sqlalchemy as sa

revision = 'f03d946d7afa'
down_revision = '72e85f336b2c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'macro_fingerprints',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('date', sa.Date, nullable=False, unique=True),
        sa.Column('regime', sa.String(20), nullable=False),
        sa.Column('overall_stress_score', sa.Numeric(5, 2)),
        sa.Column('cpi_percentile', sa.Numeric(5, 2)),
        sa.Column('fedfunds_percentile', sa.Numeric(5, 2)),
        sa.Column('unrate_percentile', sa.Numeric(5, 2)),
        sa.Column('gdp_percentile', sa.Numeric(5, 2)),
        sa.Column('t10y2y_percentile', sa.Numeric(5, 2)),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now())
    )


def downgrade():
    op.drop_table('macro_fingerprints')
