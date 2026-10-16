"""Temporal worker process. Run with:  python -m workers.worker

Hosts every workflow and activity on the configured task queue. Scale horizontally by
starting more worker processes (optionally split by task queue per worker domain).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from packages.config import get_settings
from packages.telemetry.logging import configure_logging, get_logger
from workers.compliance.activities import validate_article
from workers.content.activities import (
    complete_article_run,
    create_article_run,
    generate_article,
    generate_redteam,
    plan_brief,
)
from workers.discovery.activities import discover, normalize, track_brokers
from workers.optimization.activities import score_and_select
from workers.publishing.activities import build_site_activity
from workers.research.activities import analyze_serps, research_evidence
from workers.runs import create_day_run, create_live_run, fail_run, finalize_run, start_run
from workflows.article_generation import ArticleGenerationWorkflow
from workflows.daily_intelligence import DailyIntelligenceWorkflow
from workflows.demo_simulation import DemoSimulationWorkflow
from workflows.scheduled_daily import ScheduledDailyWorkflow

ACTIVITIES = [
    start_run, finalize_run, fail_run, create_day_run, create_live_run, track_brokers, discover, normalize, analyze_serps, score_and_select,
    create_article_run, plan_brief, research_evidence, generate_article, validate_article, complete_article_run,
    generate_redteam, build_site_activity,
]
WORKFLOWS = [DailyIntelligenceWorkflow, ArticleGenerationWorkflow, DemoSimulationWorkflow, ScheduledDailyWorkflow]


async def main() -> None:
    configure_logging()
    log = get_logger("atlas.worker")
    s = get_settings()
    client = await Client.connect(s.temporal_address, namespace=s.temporal_namespace)
    with ThreadPoolExecutor(max_workers=8) as pool:
        worker = Worker(client, task_queue=s.temporal_task_queue, workflows=WORKFLOWS, activities=ACTIVITIES,
                        activity_executor=pool, max_concurrent_activities=8)
        log.info("ATLAS Temporal worker started", extra={"task_queue": s.temporal_task_queue, "address": s.temporal_address})
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
