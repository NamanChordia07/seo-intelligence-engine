"""Workflow runs, demo control, audit log, ledger (running sheet), settings, live probe."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from apps.api import services
from apps.api.schemas import RunCreate, RunDetail, RunOut, SettingsPatch
from packages.config import get_settings
from packages.persistence.db import get_db, session_scope
from packages.persistence.models import AuditEvent, LedgerEntry, WorkflowRun
from packages.persistence.repositories import LEDGER_COLUMNS, audit, get_default_project

router = APIRouter(prefix="/api/v1", tags=["operations"])


# --------------------------------------------------------------------------- runs
@router.post("/runs", status_code=202)
async def create_run(body: RunCreate) -> dict[str, Any]:
    if body.kind == "DEMO_SIMULATION":
        return await services.start_all(wait=body.wait)
    if body.sim_day is None:
        raise ValueError("sim_day is required for DAILY_INTELLIGENCE runs in demo mode (live runs: use /discovery/live-probe)")
    return await services.start_day(body.sim_day, force=body.force, wait=body.wait)


@router.get("/runs", response_model=list[RunOut])
def list_runs(db: Session = Depends(get_db), kind: str | None = None, top_level: bool = False,
              limit: int = Query(100, le=500)) -> list[WorkflowRun]:
    p = get_default_project(db)
    stmt = select(WorkflowRun).where(WorkflowRun.project_id == p.id)
    if kind:
        stmt = stmt.where(WorkflowRun.kind == kind)
    if top_level:
        stmt = stmt.where(WorkflowRun.kind != "ARTICLE_GENERATION")
    return list(db.scalars(stmt.order_by(WorkflowRun.created_at.desc()).limit(limit)))


@router.get("/runs/{run_id}", response_model=RunDetail)
def run_detail(run_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise LookupError("run not found")
    children = list(db.scalars(select(WorkflowRun).where(WorkflowRun.parent_run_id == run.id).order_by(WorkflowRun.created_at)))
    out = RunDetail.model_validate(run)
    out.children = [RunOut.model_validate(c) for c in children]
    return out


@router.get("/runs/{run_id}/events")
def run_events(run_id: uuid.UUID, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    ids = [run_id] + list(db.scalars(select(WorkflowRun.id).where(WorkflowRun.parent_run_id == run_id)))
    events = db.scalars(select(AuditEvent).where(AuditEvent.run_id.in_(ids)).order_by(AuditEvent.created_at))
    return [_event(e) for e in events]


@router.get("/runs/{run_id}/steps-tree")
def run_steps_tree(run_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Run + child runs with their steps (one call for the Workflows timeline)."""
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise LookupError("run not found")

    def node(r: WorkflowRun) -> dict[str, Any]:
        kids = list(db.scalars(select(WorkflowRun).where(WorkflowRun.parent_run_id == r.id).order_by(WorkflowRun.created_at)))
        return {**RunOut.model_validate(r).model_dump(mode="json"),
                "steps": [{"name": st.name, "status": st.status, "attempts": st.attempts,
                           "started_at": st.started_at.isoformat(), "finished_at": st.finished_at.isoformat() if st.finished_at else None,
                           "detail": st.detail, "error": st.error} for st in r.steps],
                "children": [node(k) for k in kids]}
    return node(run)


# --------------------------------------------------------------------------- demo
@router.get("/demo/status")
def demo_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    p = get_default_project(db)
    return {"days": services.day_status(db, p), "provider_mode": get_settings().provider_mode,
            "data_label": "SIMULATED / DEMONSTRATION DATA"}


@router.post("/demo/reset")
def demo_reset() -> dict[str, Any]:
    return services.reset_demo()


@router.post("/demo/run-day/{day}", status_code=202)
async def demo_run_day(day: int, force: bool = False, wait: bool = False) -> dict[str, Any]:
    return await services.start_day(day, force=force, wait=wait, trigger="demo_button")


@router.post("/demo/run-all", status_code=202)
async def demo_run_all(wait: bool = False) -> dict[str, Any]:
    return await services.start_all(wait=wait)


# --------------------------------------------------------------------------- live probe (optional, real public data)
@router.post("/discovery/live-probe", status_code=201)
async def live_probe() -> dict[str, Any]:
    """Query the public autocomplete endpoint for a few seeds; stores REAL_PUBLIC observations (no volumes)."""
    from workers.discovery.activities import discover, normalize
    from workers.runs import finalize_run, start_run

    with session_scope() as s:
        p = get_default_project(s)
        run = WorkflowRun(project_id=p.id, kind="LIVE_PROBE", status="QUEUED", orchestrator="inline",
                          provider_mode="live", trigger="api", plan_date=datetime.now(UTC).date().isoformat())
        s.add(run)
        s.flush()
        run_id = str(run.id)

    def _run() -> dict[str, Any]:
        start_run(run_id)
        d = discover(run_id)
        normalize(run_id)
        finalize_run(run_id, d.get("provider_failures", []))
        return d

    result = await run_in_threadpool(_run)
    return {"run_id": run_id, **result}


# --------------------------------------------------------------------------- audit / ledger
def _event(e: AuditEvent) -> dict[str, Any]:
    return {"id": str(e.id), "event_type": e.event_type, "actor": e.actor, "message": e.message, "payload": e.payload,
            "run_id": str(e.run_id) if e.run_id else None, "article_id": str(e.article_id) if e.article_id else None,
            "created_at": e.created_at.isoformat()}


@router.get("/audit-events")
def audit_events(db: Session = Depends(get_db), event_type: str | None = None, q: str | None = Query(None, max_length=100),
                 limit: int = Query(300, le=2000)) -> list[dict[str, Any]]:
    p = get_default_project(db)
    stmt = select(AuditEvent).where(AuditEvent.project_id == p.id)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if q:
        stmt = stmt.where(or_(AuditEvent.message.ilike(f"%{q}%"), AuditEvent.event_type.ilike(f"%{q}%")))
    return [_event(e) for e in db.scalars(stmt.order_by(AuditEvent.created_at.desc()).limit(limit))]


def _ledger_rows(db: Session) -> list[LedgerEntry]:
    p = get_default_project(db)
    return list(db.scalars(select(LedgerEntry).where(LedgerEntry.project_id == p.id).order_by(LedgerEntry.created_at)))


def _ledger_dict(e: LedgerEntry) -> dict[str, Any]:
    out = {}
    for col in LEDGER_COLUMNS:
        v = getattr(e, col)
        if isinstance(v, datetime):
            v = v.isoformat(timespec="seconds")
        elif isinstance(v, uuid.UUID):
            v = str(v)
        out[col] = v
    out["id"] = str(e.id)
    return out


@router.get("/ledger")
def ledger_rows(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [_ledger_dict(e) for e in _ledger_rows(db)]


@router.get("/ledger/export")
def ledger_export(db: Session = Depends(get_db)) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel renders Hindi correctly
    writer = csv.writer(buf)
    writer.writerow(LEDGER_COLUMNS)
    for e in _ledger_rows(db):
        row = _ledger_dict(e)
        writer.writerow([" | ".join(row[c]) if isinstance(row[c], list) else ("" if row[c] is None else row[c])
                         for c in LEDGER_COLUMNS])
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="atlas-content-ledger-{stamp}.csv"'})


# --------------------------------------------------------------------------- settings
@router.get("/settings")
def get_project_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
    p = get_default_project(db)
    s = get_settings()
    return {"project": {"name": p.name, "domain": p.domain, "default_locale": p.default_locale, "settings": p.settings},
            "runtime": {"provider_mode": s.provider_mode, "llm_provider": s.llm_provider, "llm_model": s.llm_model if s.llm_provider != "demo" else None,
                        "orchestrator": s.orchestrator, "temporal_ui_url": s.temporal_ui_url, "live_research": s.live_research,
                        "searxng_configured": bool(s.searxng_url), "llm_advisory_review": s.llm_advisory_review}}


@router.patch("/settings")
def patch_settings(body: SettingsPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    p = get_default_project(db)
    current = dict(p.settings or {})
    changes = body.model_dump(exclude_none=True, exclude={"actor"})
    current.update(changes)
    p.settings = current
    audit(db, p.id, "SETTINGS_CHANGED", f"Project settings changed by {body.actor}: {changes}", actor=body.actor, payload=changes)
    db.flush()
    return {"settings": p.settings}
