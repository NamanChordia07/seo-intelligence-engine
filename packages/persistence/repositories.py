"""Persistence services. Route handlers and workers use these instead of ad-hoc SQL."""

from __future__ import annotations

import traceback
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from packages.persistence.models import (
    Article,
    AuditEvent,
    LedgerEntry,
    Project,
    Tenant,
    WorkflowRun,
    WorkflowStep,
)
from packages.telemetry.logging import get_logger

log = get_logger("atlas.persistence")

DEFAULT_PROJECT_SLUG = "india-trading-demo"


def now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- project
def get_default_project(session: Session) -> Project:
    project = session.scalar(select(Project).where(Project.slug == DEFAULT_PROJECT_SLUG))
    if project is None:
        from packages.persistence.seed import seed

        seed(session)
        project = session.scalar(select(Project).where(Project.slug == DEFAULT_PROJECT_SLUG))
    assert project is not None
    return project


def get_tenant(session: Session, tenant_id: uuid.UUID) -> Tenant | None:
    return session.get(Tenant, tenant_id)


# --------------------------------------------------------------------------- audit
def audit(
    session: Session, project_id: uuid.UUID, event_type: str, message: str, *, run_id: uuid.UUID | None = None,
    article_id: uuid.UUID | None = None, actor: str = "system", payload: dict[str, Any] | None = None,
) -> AuditEvent:
    ev = AuditEvent(project_id=project_id, run_id=run_id, article_id=article_id, event_type=event_type, actor=actor,
                    message=message, payload=payload or {})
    session.add(ev)
    log.info(message, extra={"event_type": event_type, "run_id": str(run_id) if run_id else None,
                             "article_id": str(article_id) if article_id else None})
    return ev


# --------------------------------------------------------------------------- ledger
def ledger(session: Session, project_id: uuid.UUID, entry_type: str, **fields: Any) -> LedgerEntry:
    entry = LedgerEntry(project_id=project_id, entry_type=entry_type, **fields)
    session.add(entry)
    return entry


LEDGER_COLUMNS = [
    "created_at", "plan_date", "sim_day", "entry_type", "run_id", "article_id", "opportunity_id", "target_keyword",
    "language", "locale", "intent", "intent_key", "opportunity_score", "target_slug", "content_status",
    "compliance_status", "publication_eligibility", "workflow_status", "article_version", "evidence_sources",
    "note", "updated_at",
]


# --------------------------------------------------------------------------- runs / steps
def get_run(session: Session, run_id: uuid.UUID | str) -> WorkflowRun:
    run = session.get(WorkflowRun, uuid.UUID(str(run_id)))
    if run is None:
        raise LookupError(f"workflow run {run_id} not found")
    return run


@contextmanager
def step(session: Session, run_id: uuid.UUID, name: str) -> Iterator[dict[str, Any]]:
    """Record a workflow step (idempotent per run+name; retries increment `attempts`)."""
    existing = session.scalar(select(WorkflowStep).where(WorkflowStep.run_id == run_id, WorkflowStep.name == name))
    if existing is None:
        existing = WorkflowStep(run_id=run_id, name=name, status="RUNNING", started_at=now(), attempts=1)
        session.add(existing)
    else:
        existing.attempts += 1
        existing.status = "RUNNING"
        existing.started_at = now()
        existing.error = None
    session.flush()
    detail: dict[str, Any] = {}
    try:
        yield detail
    except Exception as exc:
        existing.status = "FAILED"
        existing.error = f"{type(exc).__name__}: {exc}"
        existing.detail = {**detail, "traceback": traceback.format_exc(limit=4)}
        existing.finished_at = now()
        raise
    else:
        existing.status = "SKIPPED" if detail.get("skipped") else "COMPLETED"
        existing.detail = detail
        existing.finished_at = now()


def mark_run(session: Session, run: WorkflowRun, status: str, error: str | None = None, **stats: Any) -> None:
    run.status = status
    if status == "RUNNING" and run.started_at is None:
        run.started_at = now()
    if status in ("COMPLETED", "FAILED", "PARTIAL"):
        run.finished_at = now()
    if error:
        run.error = error[:4000]
    if stats:
        run.stats = {**(run.stats or {}), **stats}


# --------------------------------------------------------------------------- articles
def generated_articles(session: Session, project_id: uuid.UUID, include_test: bool = False) -> list[Article]:
    q = select(Article).where(Article.project_id == project_id, Article.origin == "GENERATED")
    if not include_test:
        q = q.where(Article.is_test_fixture.is_(False))
    return list(session.scalars(q.order_by(Article.created_at)))


def count(session: Session, model: Any, *where: Any) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where)) or 0


# --------------------------------------------------------------------------- reset
PROJECT_TABLES_IN_DELETE_ORDER = [
    "content_ledger", "audit_events", "internal_links", "compliance_decisions", "evidence_claims", "article_versions",
    "intent_reservations", "content_briefs", "content_plans", "opportunities", "serp_snapshots", "keyword_candidates",
    "intent_clusters", "search_observations", "evidence_sources", "articles", "workflow_steps", "workflow_runs",
]


def reset_project_data(session: Session, project_id: uuid.UUID) -> None:
    """Wipe all generated state for a project (entities/tenant kept). Inventory is re-seeded by caller."""
    for table in PROJECT_TABLES_IN_DELETE_ORDER:
        if table == "workflow_steps":
            session.execute(text("DELETE FROM workflow_steps WHERE run_id IN (SELECT id FROM workflow_runs WHERE project_id = :p)"),
                            {"p": project_id})
        elif table == "article_versions":
            session.execute(text("DELETE FROM article_versions WHERE article_id IN (SELECT id FROM articles WHERE project_id = :p)"),
                            {"p": project_id})
        else:
            session.execute(text(f"DELETE FROM {table} WHERE project_id = :p"), {"p": project_id})  # noqa: S608 - fixed table list
    session.flush()


def delete_where(session: Session, model: Any, *where: Any) -> None:
    session.execute(delete(model).where(*where))
