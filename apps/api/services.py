"""Application services used by the API (and CLI). Keeps route handlers thin."""

from __future__ import annotations

import shutil
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from packages.config import get_settings
from packages.persistence.db import session_scope
from packages.persistence.models import Article, Project, WorkflowRun
from packages.persistence.repositories import audit, get_default_project, reset_project_data
from packages.persistence.seed import seed_inventory
from packages.providers.fixtures import available_days, day_config
from workflows import engine


class Conflict(RuntimeError):
    """409 - request conflicts with current state."""


def day_status(session: Session, project: Project) -> list[dict[str, Any]]:
    out = []
    for day in available_days():
        runs = list(session.scalars(select(WorkflowRun).where(
            WorkflowRun.project_id == project.id, WorkflowRun.kind == "DAILY_INTELLIGENCE", WorkflowRun.sim_day == day)
            .order_by(WorkflowRun.created_at.desc())))
        latest = runs[0] if runs else None
        arts = list(session.scalars(select(Article).where(Article.project_id == project.id, Article.sim_day == day,
                                                          Article.origin == "GENERATED")))
        cfg = day_config(day)
        out.append({
            "day": day, "date": cfg["date"], "narrative": cfg.get("narrative"), "runs": len(runs),
            "latest_run_id": str(latest.id) if latest else None, "status": latest.status if latest else "NOT_RUN",
            "articles": len([a for a in arts if not a.is_test_fixture]),
            "redteam_articles": len([a for a in arts if a.is_test_fixture]),
            "observations_fixture": len(cfg["observations"]), "data_label": "SIMULATED / DEMONSTRATION DATA",
        })
    return out


async def start_day(sim_day: int, *, force: bool = False, wait: bool = False, trigger: str = "api") -> dict[str, Any]:
    if sim_day not in available_days():
        raise LookupError(f"No simulated fixture for day {sim_day}")
    with session_scope() as s:
        project = get_default_project(s)
        days = {d["day"]: d for d in day_status(s, project)}
        if any(d["status"] in ("QUEUED", "RUNNING") for d in days.values()):
            raise Conflict("Another demo day is currently running - wait for it to finish")
        if not force:
            if sim_day > 1 and days.get(sim_day - 1, {}).get("status") not in ("COMPLETED", "PARTIAL"):
                raise Conflict(f"Run Day {sim_day - 1} first (later days build on earlier content inventory)")
            if days[sim_day]["status"] in ("COMPLETED", "PARTIAL"):
                raise Conflict(f"Day {sim_day} already completed. Re-run with force=true to demonstrate duplicate prevention.")
        project_id = project.id
    orchestrator, why = ("inline", "synchronous request") if wait else await engine.choose_orchestrator()
    try:
        with session_scope() as s:
            run = WorkflowRun(project_id=project_id, kind="DAILY_INTELLIGENCE", sim_day=sim_day,
                              plan_date=day_config(sim_day)["date"], status="QUEUED", orchestrator=orchestrator,
                              provider_mode=get_settings().provider_mode, trigger=trigger,
                              stats={"orchestrator_reason": why, "rerun": force})
            s.add(run)
            s.flush()
            run_id = str(run.id)
            audit(s, project_id, "RUN_QUEUED", f"Day {sim_day} queued via {orchestrator} ({why})", run_id=run.id)
    except IntegrityError as exc:
        raise Conflict(f"Day {sim_day} already has an active run (database guard)") from exc
    await dispatch("DailyIntelligenceWorkflow", [run_id], run_id, orchestrator, wait, engine.run_daily_inline, run_id)
    return {"run_id": run_id, "orchestrator": orchestrator, "reason": why}


async def start_all(*, wait: bool = False) -> dict[str, Any]:
    with session_scope() as s:
        project = get_default_project(s)
        days = day_status(s, project)
        if any(d["status"] in ("QUEUED", "RUNNING") for d in days):
            raise Conflict("A demo day is currently running")
        if any(d["status"] in ("COMPLETED", "PARTIAL") for d in days):
            raise Conflict("Some days already ran - reset the demo first to run the full simulation")
        project_id = project.id
    orchestrator, why = ("inline", "synchronous request") if wait else await engine.choose_orchestrator()
    with session_scope() as s:
        run = WorkflowRun(project_id=project_id, kind="DEMO_SIMULATION", status="QUEUED", orchestrator=orchestrator,
                          provider_mode=get_settings().provider_mode, trigger="api", stats={"orchestrator_reason": why})
        s.add(run)
        s.flush()
        run_id = str(run.id)
    days_list = available_days()
    await dispatch("DemoSimulationWorkflow", [run_id, days_list], run_id, orchestrator, wait, engine.run_demo_inline,
                   run_id, days_list)
    return {"run_id": run_id, "orchestrator": orchestrator, "reason": why}


async def dispatch(workflow: str, args: list[Any], run_id: str, orchestrator: str, wait: bool, inline_fn, *inline_args) -> None:
    if wait:
        await run_in_threadpool(inline_fn, *inline_args)
        return
    if orchestrator == "temporal":
        wf_id = await engine.start_temporal(workflow, args, f"atlas-{workflow}-{run_id}")
        with session_scope() as s:
            run = s.get(WorkflowRun, uuid.UUID(run_id))
            run.temporal_workflow_id = wf_id
        return
    engine.spawn(inline_fn, *inline_args)


def reset_demo() -> dict[str, Any]:
    with session_scope() as s:
        project = get_default_project(s)
        active = s.scalar(select(WorkflowRun).where(WorkflowRun.project_id == project.id,
                                                    WorkflowRun.status.in_(["QUEUED", "RUNNING"])))
        if active:
            raise Conflict("Cannot reset while a run is active")
        reset_project_data(s, project.id)
        seed_inventory(s, project)
        settings = dict(project.settings or {})
        settings["india_authorization_status"] = "UNKNOWN"
        project.settings = settings
        audit(s, project.id, "DEMO_RESET", "Demo data reset; simulated inventory re-seeded", actor="demo-user")
    out = get_settings().output_path
    if out.exists():
        for child in out.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            elif child.name != ".gitkeep":
                child.unlink()
    return {"reset": True}
