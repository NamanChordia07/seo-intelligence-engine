"""Run lifecycle activities (start / finalize / fail / child-run creation)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from temporalio import activity

from packages.persistence.db import session_scope
from packages.persistence.models import Article, OpportunityRow, WorkflowRun
from packages.persistence.repositories import audit, get_run, mark_run
from packages.providers.fixtures import day_config


@activity.defn(name="start_run")
def start_run(run_id: str) -> dict[str, Any]:
    with session_scope() as s:
        run = get_run(s, run_id)
        if run.status in ("COMPLETED", "FAILED"):
            return {"status": run.status, "already_finished": True}
        mark_run(s, run, "RUNNING")
        audit(s, run.project_id, "RUN_STARTED", f"{run.kind} started (day {run.sim_day}, orchestrator={run.orchestrator})",
              run_id=run.id)
        redteam = bool(run.sim_day and day_config(run.sim_day).get("redteam"))
        return {"status": "RUNNING", "sim_day": run.sim_day, "redteam": redteam}


@activity.defn(name="finalize_run")
def finalize_run(run_id: str, failures: list[str]) -> dict[str, Any]:
    with session_scope() as s:
        run = get_run(s, run_id)
        run_ids = [run.id] + list(s.scalars(select(WorkflowRun.id).where(
            WorkflowRun.parent_run_id == run.id, WorkflowRun.kind == "DAILY_INTELLIGENCE")))
        arts = list(s.scalars(select(Article).where(Article.run_id.in_(run_ids))))
        real = [a for a in arts if not a.is_test_fixture]
        opps = list(s.scalars(select(OpportunityRow).where(OpportunityRow.run_id.in_(run_ids))))
        status_counts: dict[str, int] = {}
        for o in opps:
            status_counts[o.status] = status_counts.get(o.status, 0) + 1
        compliance: dict[str, int] = {}
        for a in arts:
            compliance[a.compliance_status] = compliance.get(a.compliance_status, 0) + 1
        stats = {
            "articles_generated": len(real), "redteam_articles": len(arts) - len(real),
            "opportunities": len(opps), "opportunity_status": status_counts, "compliance": compliance,
            "languages": sorted({a.language for a in real}), "failures": failures,
        }
        status = "PARTIAL" if failures else "COMPLETED"
        mark_run(s, run, status, error="; ".join(failures) if failures else None, **stats)
        audit(s, run.project_id, f"RUN_{status}",
              f"{run.kind} day {run.sim_day} {status.lower()}: {len(real)} new page(s), {len(opps)} opportunities scored",
              run_id=run.id, payload=stats)
        return stats


@activity.defn(name="fail_run")
def fail_run(run_id: str, error: str) -> None:
    with session_scope() as s:
        run = get_run(s, run_id)
        mark_run(s, run, "FAILED", error=error)
        audit(s, run.project_id, "RUN_FAILED", f"{run.kind} failed: {error[:300]}", run_id=run.id)


@activity.defn(name="create_day_run")
def create_day_run(parent_run_id: str, sim_day: int) -> str:
    with session_scope() as s:
        parent = get_run(s, parent_run_id)
        existing = s.scalar(select(WorkflowRun).where(WorkflowRun.parent_run_id == parent.id,
                                                      WorkflowRun.kind == "DAILY_INTELLIGENCE",
                                                      WorkflowRun.sim_day == sim_day))
        if existing:
            return str(existing.id)
        child = WorkflowRun(project_id=parent.project_id, parent_run_id=parent.id, kind="DAILY_INTELLIGENCE",
                            sim_day=sim_day, plan_date=day_config(sim_day)["date"], status="QUEUED",
                            orchestrator=parent.orchestrator, provider_mode=parent.provider_mode, trigger="demo_simulation")
        s.add(child)
        s.flush()
        return str(child.id)
