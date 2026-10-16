"""Partial unique index: at most one active daily run per simulated day.

Revision ID: b1c2d3e4f5a6
Revises: 8e29a5bdd872
Create Date: 2026-10-16
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "8e29a5bdd872"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_active_daily_run ON workflow_runs (project_id, sim_day) "
        "WHERE status IN ('QUEUED', 'RUNNING') AND kind = 'DAILY_INTELLIGENCE'"
    )
    # Semantic search over articles / candidates (pgvector cosine)
    op.execute("CREATE INDEX IF NOT EXISTS ix_articles_embedding ON articles USING hnsw (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_candidates_embedding ON keyword_candidates USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidates_embedding")
    op.execute("DROP INDEX IF EXISTS ix_articles_embedding")
    op.execute("DROP INDEX IF EXISTS uq_active_daily_run")
