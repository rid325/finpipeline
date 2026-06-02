"""create initial tables

Revision ID: 72e85f336b2c
Revises:
Create Date: 2026-06-02

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '72e85f336b2c'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # stock prices table
    op.create_table(
        'stock_prices',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('ticker', sa.String(10), nullable=False),
        sa.Column('date', sa.Date, nullable=False),
        sa.Column('open', sa.Numeric(10, 2)),
        sa.Column('high', sa.Numeric(10, 2)),
        sa.Column('low', sa.Numeric(10, 2)),
        sa.Column('close', sa.Numeric(10, 2)),
        sa.Column('volume', sa.BigInteger),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint('ticker', 'date', name='uq_ticker_date')
    )

    # economic indicators table
    op.create_table(
        'economic_indicators',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('indicator', sa.String(50), nullable=False),
        sa.Column('date', sa.Date, nullable=False),
        sa.Column('value', sa.Numeric(15, 4)),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint('indicator', 'date', name='uq_indicator_date')
    )

    # pipeline runs table
    op.create_table(
        'pipeline_runs',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('source', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('records_fetched', sa.Integer, default=0),
        sa.Column('error_message', sa.Text),
        sa.Column('started_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime)
    )


def downgrade():
    op.drop_table('pipeline_runs')
    op.drop_table('economic_indicators')
    op.drop_table('stock_prices')
