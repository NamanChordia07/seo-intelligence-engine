"""Broker demand snapshots + at most one active LIVE daily run per plan date.

Revision ID: c7d8e9f0a1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broker_demand_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("captured_on", sa.String(10), nullable=False),
        sa.Column("entity_key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("demand_index", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("tracked", sa.Boolean(), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("components", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "entity_key", name="uq_broker_demand_run_entity"),
    )
    op.create_index("ix_broker_demand_snapshots_project_id", "broker_demand_snapshots", ["project_id"])
    op.create_index("ix_broker_demand_snapshots_run_id", "broker_demand_snapshots", ["run_id"])
    op.create_index("ix_broker_demand_project_date", "broker_demand_snapshots", ["project_id", "captured_on"])
    # Simulated days are guarded by uq_active_daily_run(sim_day); live runs (sim_day NULL) are guarded per plan date.
    op.execute(
        "CREATE UNIQUE INDEX uq_active_live_run ON workflow_runs (project_id, plan_date) "
        "WHERE status IN ('QUEUED', 'RUNNING') AND kind = 'DAILY_INTELLIGENCE' AND sim_day IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_active_live_run")
    op.drop_table("broker_demand_snapshots")
