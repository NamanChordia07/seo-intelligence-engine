"""Dashboard, search intelligence (observations / candidates / clusters), opportunities."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.schemas import OpportunityOut, RunOut
from apps.api.services import day_status
from packages.persistence.db import get_db
from packages.persistence.models import (
    Article,
    ComplianceDecision,
    ContentBriefRow,
    IntentCluster,
    KeywordCandidateRow,
    OpportunityRow,
    SearchObservationRow,
    SerpSnapshotRow,
    WorkflowRun,
)
from packages.persistence.repositories import get_default_project

router = APIRouter(prefix="/api/v1", tags=["intelligence"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict[str, Any]:
    p = get_default_project(db)
    obs_total = db.scalar(select(func.count()).select_from(SearchObservationRow).where(SearchObservationRow.project_id == p.id)) or 0
    obs_by_lang = dict(db.execute(select(SearchObservationRow.language, func.count()).where(
        SearchObservationRow.project_id == p.id).group_by(SearchObservationRow.language)).all())
    obs_by_source_type = dict(db.execute(select(SearchObservationRow.source_type, func.count()).where(
        SearchObservationRow.project_id == p.id).group_by(SearchObservationRow.source_type)).all())
    cand_total = db.scalar(select(func.count()).select_from(KeywordCandidateRow).where(KeywordCandidateRow.project_id == p.id)) or 0
    clusters = db.scalar(select(func.count()).select_from(IntentCluster).where(IntentCluster.project_id == p.id)) or 0
    opp_by_status = dict(db.execute(select(OpportunityRow.status, func.count()).where(
        OpportunityRow.project_id == p.id).group_by(OpportunityRow.status)).all())
    arts = list(db.scalars(select(Article).where(Article.project_id == p.id, Article.origin == "GENERATED")))
    real = [a for a in arts if not a.is_test_fixture]
    compliance = {"PASS": 0, "REVIEW": 0, "BLOCK": 0}
    for a in arts:
        if a.compliance_status in compliance:
            compliance[a.compliance_status] += 1
    art_by_lang: dict[str, int] = {}
    for a in real:
        art_by_lang[a.language] = art_by_lang.get(a.language, 0) + 1
    recent = list(db.scalars(select(WorkflowRun).where(WorkflowRun.project_id == p.id, WorkflowRun.parent_run_id.is_(None))
                             .order_by(WorkflowRun.created_at.desc()).limit(6)))
    top = list(db.scalars(select(OpportunityRow).where(OpportunityRow.project_id == p.id, OpportunityRow.status == "SELECTED")
                          .order_by(OpportunityRow.score.desc()).limit(6)))
    human_approved = db.scalar(select(func.count()).select_from(ComplianceDecision).where(
        ComplianceDecision.project_id == p.id, ComplianceDecision.decided_by.like("human:%"))) or 0
    return {
        "project": {"id": str(p.id), "name": p.name, "domain": p.domain, "settings": p.settings},
        "counts": {
            "observations": obs_total, "candidates": cand_total, "intent_clusters": clusters,
            "opportunities": sum(opp_by_status.values()), "articles_generated": len(real),
            "redteam_articles": len(arts) - len(real),
            "inventory_pages": db.scalar(select(func.count()).select_from(Article).where(Article.project_id == p.id, Article.origin == "INVENTORY")) or 0,
            "human_approvals": human_approved,
        },
        "observations_by_language": obs_by_lang, "observations_by_source_type": obs_by_source_type,
        "opportunities_by_status": opp_by_status, "articles_by_language": art_by_lang, "compliance": compliance,
        "recent_runs": [RunOut.model_validate(r).model_dump(mode="json") for r in recent],
        "top_opportunities": [{"id": str(o.id), "keyword": o.keyword, "language": o.language, "score": o.score,
                               "why": o.why[:3], "sim_day": o.sim_day, "article_id": str(o.article_id) if o.article_id else None}
                              for o in top],
        "days": day_status(db, p),
        "data_label": "Search signals are SIMULATED demonstration data; evidence sources are real public documents (snapshots).",
    }


@router.get("/observations")
def observations(
    db: Session = Depends(get_db), language: str | None = None, source_type: str | None = None,
    day: int | None = None, q: str | None = Query(default=None, max_length=100), limit: int = Query(200, le=1000),
) -> list[dict[str, Any]]:
    p = get_default_project(db)
    stmt = select(SearchObservationRow).where(SearchObservationRow.project_id == p.id)
    if language:
        stmt = stmt.where(SearchObservationRow.language == language)
    if source_type:
        stmt = stmt.where(SearchObservationRow.source_type == source_type)
    if day:
        stmt = stmt.where(SearchObservationRow.sim_day == day)
    if q:
        stmt = stmt.where(SearchObservationRow.query.ilike(f"%{q}%"))
    rows = db.scalars(stmt.order_by(SearchObservationRow.sim_day.desc().nullsfirst(), SearchObservationRow.demand_proxy.desc().nullslast()).limit(limit))
    return [{
        "id": str(o.id), "query": o.query, "normalized_query": o.normalized_query, "language": o.language, "locale": o.locale,
        "source": o.source, "source_type": o.source_type, "confidence": o.confidence, "demand_proxy": o.demand_proxy,
        "trend_velocity": o.trend_velocity, "seed": o.seed, "entity_keys": o.entity_keys, "is_news": o.is_news,
        "sim_day": o.sim_day, "observed_at": o.observed_at.isoformat(), "run_id": str(o.run_id) if o.run_id else None,
    } for o in rows]


@router.get("/candidates")
def candidates(db: Session = Depends(get_db), language: str | None = None) -> list[dict[str, Any]]:
    p = get_default_project(db)
    stmt = select(KeywordCandidateRow).where(KeywordCandidateRow.project_id == p.id)
    if language:
        stmt = stmt.where(KeywordCandidateRow.language == language)
    return [{
        "id": str(c.id), "query": c.display_query, "normalized_query": c.normalized_query, "language": c.language,
        "theme": c.theme, "intent": c.intent, "intent_key": c.intent_key, "entity_keys": c.entity_keys,
        "concept_tokens": c.concept_tokens, "demand_proxy": c.demand_proxy, "trend_velocity": c.trend_velocity,
        "source_types": c.source_types, "observation_count": c.observation_count, "first_seen_day": c.first_seen_day,
        "last_seen_day": c.last_seen_day, "is_news": c.is_news,
    } for c in db.scalars(stmt.order_by(KeywordCandidateRow.intent_key))]


@router.get("/clusters")
def clusters(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    p = get_default_project(db)
    return [{"id": str(c.id), "intent_key": c.intent_key, "label": c.label, "theme": c.theme, "intent": c.intent,
             "entity_keys": c.entity_keys, "languages": c.languages, "candidate_count": c.candidate_count}
            for c in db.scalars(select(IntentCluster).where(IntentCluster.project_id == p.id).order_by(IntentCluster.intent_key))]


@router.get("/opportunities", response_model=list[OpportunityOut])
def opportunities(db: Session = Depends(get_db), status: str | None = None, day: int | None = None,
                  language: str | None = None, run_id: uuid.UUID | None = None) -> list[OpportunityRow]:
    p = get_default_project(db)
    stmt = select(OpportunityRow).where(OpportunityRow.project_id == p.id)
    if status:
        stmt = stmt.where(OpportunityRow.status == status)
    if day:
        stmt = stmt.where(OpportunityRow.sim_day == day)
    if language:
        stmt = stmt.where(OpportunityRow.language == language)
    if run_id:
        stmt = stmt.where(OpportunityRow.run_id == run_id)
    return list(db.scalars(stmt.order_by(OpportunityRow.sim_day.desc().nullsfirst(), OpportunityRow.rank)))


@router.get("/opportunities/{opportunity_id}")
def opportunity_detail(opportunity_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    o = db.get(OpportunityRow, opportunity_id)
    if o is None:
        raise LookupError("opportunity not found")
    snap = db.scalar(select(SerpSnapshotRow).where(SerpSnapshotRow.run_id == o.run_id, SerpSnapshotRow.candidate_id == o.candidate_id))
    brief = db.scalar(select(ContentBriefRow).where(ContentBriefRow.opportunity_id == o.id))
    conflict = db.get(Article, o.conflicting_article_id) if o.conflicting_article_id else None
    return {
        "opportunity": OpportunityOut.model_validate(o).model_dump(mode="json"),
        "serp": {"query": snap.query, "source": snap.source, "source_type": snap.source_type, "results": snap.results,
                 "analysis": snap.analysis, "captured_at": snap.captured_at.isoformat()} if snap else None,
        "brief": brief.brief if brief else None,
        "conflicting_article": {"id": str(conflict.id), "title": conflict.title, "slug": conflict.slug,
                                "language": conflict.language, "origin": conflict.origin} if conflict else None,
    }
