"""add job run metadata

Revision ID: 86c7434a3f20
Revises: f03d946d7afa
Create Date: 2026-10-17
"""
from alembic import op
import sqlalchemy as sa

revision = "86c7434a3f20"
down_revision = "f03d946d7afa"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pipeline_runs", sa.Column("job_name", sa.String(80)))
    op.add_column("pipeline_runs", sa.Column("duration_ms", sa.Integer))
    op.create_index("ix_pipeline_runs_job_started", "pipeline_runs", ["job_name", "started_at"])


def downgrade():
    op.drop_index("ix_pipeline_runs_job_started", table_name="pipeline_runs")
    op.drop_column("pipeline_runs", "duration_ms")
    op.drop_column("pipeline_runs", "job_name")
