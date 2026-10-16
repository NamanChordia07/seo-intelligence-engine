"""Orchestration dispatcher.

* Temporal (preferred): durable workflows, retries, history, Temporal UI.
* Inline fallback: identical activity sequence executed in-process (background thread),
  used automatically when the Temporal server or a worker is unreachable, and in tests.

Both paths call the same idempotent activity functions, so behaviour is identical.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from packages.config import get_settings
from packages.telemetry.logging import get_logger
from workers.compliance.activities import validate_article
from workers.content.activities import (
    complete_article_run,
    create_article_run,
    generate_article,
    generate_redteam,
    plan_brief,
)
from workers.discovery.activities import discover, normalize
from workers.optimization.activities import score_and_select
from workers.research.activities import analyze_serps, research_evidence
from workers.runs import create_day_run, fail_run, finalize_run, start_run

log = get_logger("atlas.engine")


# --------------------------------------------------------------------------- inline
def run_article_inline(run_id: str, opportunity_id: str) -> dict[str, Any]:
    child = create_article_run(run_id, opportunity_id)
    try:
        plan_brief(child, opportunity_id)
        research_evidence(child, opportunity_id)
        gen = generate_article(child, opportunity_id)
        res = validate_article(child, gen["article_id"])
        complete_article_run(child, True, "")
        return {"article_id": gen["article_id"], "compliance": res.get("status"), "child_run_id": child}
    except Exception as exc:
        complete_article_run(child, False, f"{type(exc).__name__}: {exc}")
        raise


def run_daily_inline(run_id: str) -> dict[str, Any]:
    try:
        started = start_run(run_id)
        discover(run_id)
        normalize(run_id)
        analyze_serps(run_id)
        plan = score_and_select(run_id)
        failures: list[str] = []
        for opp_id in plan["selected"]:
            try:
                run_article_inline(run_id, opp_id)
            except Exception as exc:  # noqa: BLE001 - one failed page must not sink the day
                log.exception("article pipeline failed", extra={"run_id": run_id, "opportunity_id": opp_id})
                failures.append(f"article {opp_id}: {type(exc).__name__}: {exc}")
        if started.get("redteam"):
            red = generate_redteam(run_id)
            validate_article(run_id, red["article_id"])
        return finalize_run(run_id, failures)
    except Exception as exc:
        log.exception("daily run failed", extra={"run_id": run_id})
        fail_run(run_id, f"{type(exc).__name__}: {exc}")
        raise


def run_demo_inline(parent_run_id: str, days: list[int]) -> dict[str, Any]:
    start_run(parent_run_id)
    failures: list[str] = []
    for day in days:
        day_run = create_day_run(parent_run_id, day)
        try:
            run_daily_inline(day_run)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"day {day}: {exc}")
            break
    return finalize_run(parent_run_id, failures)


def spawn(target: Any, *args: Any) -> None:
    def _safe() -> None:
        try:
            target(*args)
        except Exception:  # noqa: BLE001 - already recorded on the run
            log.exception("inline orchestration failed")

    threading.Thread(target=_safe, daemon=True, name=f"atlas-inline-{args[0]}").start()


# --------------------------------------------------------------------------- temporal
async def temporal_client():
    from temporalio.client import Client

    s = get_settings()
    return await asyncio.wait_for(Client.connect(s.temporal_address, namespace=s.temporal_namespace), timeout=3)


async def temporal_worker_available() -> tuple[bool, str]:
    """True only if the Temporal server is reachable AND at least one worker polls the task queue."""
    try:
        from temporalio.api.enums.v1 import TaskQueueType
        from temporalio.api.taskqueue.v1 import TaskQueue
        from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest

        client = await temporal_client()
        s = get_settings()
        resp = await client.workflow_service.describe_task_queue(DescribeTaskQueueRequest(
            namespace=s.temporal_namespace, task_queue=TaskQueue(name=s.temporal_task_queue),
            task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW))
        if not resp.pollers:
            return False, "Temporal reachable but no worker is polling the task queue"
        return True, f"{len(resp.pollers)} worker poller(s)"
    except Exception as exc:  # noqa: BLE001
        return False, f"Temporal unavailable: {type(exc).__name__}"


async def choose_orchestrator() -> tuple[str, str]:
    mode = get_settings().orchestrator
    if mode == "inline":
        return "inline", "configured inline"
    ok, why = await temporal_worker_available()
    if ok:
        return "temporal", why
    if mode == "temporal":
        raise RuntimeError(why)
    return "inline", f"fallback: {why}"


async def start_temporal(workflow_name: str, args: list[Any], workflow_id: str) -> str:
    client = await temporal_client()
    handle = await client.start_workflow(workflow_name, args=args, id=workflow_id,
                                         task_queue=get_settings().temporal_task_queue)
    return handle.id
