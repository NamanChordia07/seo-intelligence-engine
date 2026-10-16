"""Articles, evidence, compliance, internal-link graph."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.schemas import ApproveIn, ArticleSummary, ComplianceCheckIn
from apps.api.services import Conflict
from packages.contracts.enums import AuthorizationStatus, ContentClass, ContentType, Language
from packages.domain.compliance import ComplianceInput, rule_catalog, run_compliance
from packages.domain.seo import article_path
from packages.persistence.db import get_db
from packages.persistence.models import (
    Article,
    ComplianceDecision,
    EvidenceClaim,
    EvidenceSource,
    InternalLink,
    OpportunityRow,
)
from packages.persistence.repositories import audit, get_default_project
from packages.providers.simulated import FixtureEvidenceProvider
from workers.compliance.activities import apply_report, evaluate_article, ledger_for_article

router = APIRouter(prefix="/api/v1", tags=["content"])


def _article(db: Session, article_id: uuid.UUID) -> Article:
    a = db.get(Article, article_id)
    if a is None:
        raise LookupError("article not found")
    return a


def _decision_out(d: ComplianceDecision) -> dict[str, Any]:
    return {"id": str(d.id), "article_id": str(d.article_id) if d.article_id else None, "article_version": d.article_version,
            "status": d.status, "publication_eligibility": d.publication_eligibility, "content_class": d.content_class,
            "rule_results": d.rule_results, "reasons": d.reasons, "llm_advisory": d.llm_advisory,
            "decided_by": d.decided_by, "reviewer_note": d.reviewer_note, "created_at": d.created_at.isoformat()}


@router.get("/articles", response_model=list[ArticleSummary])
def list_articles(db: Session = Depends(get_db), language: str | None = None, status: str | None = None,
                  origin: str | None = None, include_test: bool = True) -> list[Article]:
    p = get_default_project(db)
    stmt = select(Article).where(Article.project_id == p.id)
    if language:
        stmt = stmt.where(Article.language == language)
    if status:
        stmt = stmt.where(Article.status == status)
    if origin:
        stmt = stmt.where(Article.origin == origin)
    if not include_test:
        stmt = stmt.where(Article.is_test_fixture.is_(False))
    return list(db.scalars(stmt.order_by(Article.origin.desc(), Article.sim_day.nullsfirst(), Article.created_at)))


@router.get("/articles/{article_id}")
def article_detail(article_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    a = _article(db, article_id)
    v = a.versions[-1]
    outbound = list(db.scalars(select(InternalLink).where(InternalLink.source_article_id == a.id)))
    inbound = list(db.scalars(select(InternalLink).where(InternalLink.target_article_id == a.id)))

    def link_out(link: InternalLink, other_id: uuid.UUID) -> dict[str, Any]:
        other = db.get(Article, other_id)
        return {"id": str(link.id), "article_id": str(other.id), "title": other.title, "slug": other.slug,
                "language": other.language, "origin": other.origin, "path": article_path(other.language, other.slug),
                "anchor_text": link.anchor_text, "score": link.score, "reason": link.reason, "direction": link.direction,
                "status": link.status}

    latest = db.scalar(select(ComplianceDecision).where(ComplianceDecision.article_id == a.id)
                       .order_by(ComplianceDecision.created_at.desc()))
    opp = db.get(OpportunityRow, a.opportunity_id) if a.opportunity_id else None
    return {
        "article": ArticleSummary.model_validate(a).model_dump(mode="json"),
        "path": article_path(a.language, a.slug),
        "version": {"version": v.version, "markdown": v.markdown, "frontmatter": v.frontmatter, "seo": v.seo,
                    "brief": v.brief, "word_count": v.word_count, "content_hash": v.content_hash,
                    "generator": v.generator, "change_note": v.change_note, "created_at": v.created_at.isoformat()},
        "versions": [{"version": x.version, "generator": x.generator, "word_count": x.word_count,
                      "content_hash": x.content_hash[:12], "change_note": x.change_note, "created_at": x.created_at.isoformat()}
                     for x in a.versions],
        "links_out": [link_out(link, link.target_article_id) for link in outbound],
        "links_in": [link_out(link, link.source_article_id) for link in inbound],
        "compliance": _decision_out(latest) if latest else None,
        "opportunity": {"id": str(opp.id), "score": opp.score, "why": opp.why, "components": opp.components,
                        "cannibalization": opp.cannibalization} if opp else None,
    }


@router.get("/articles/{article_id}/markdown", response_class=PlainTextResponse)
def article_markdown(article_id: uuid.UUID, db: Session = Depends(get_db)) -> PlainTextResponse:
    a = _article(db, article_id)
    return PlainTextResponse(a.versions[-1].markdown, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{a.slug}.md"'})


@router.get("/articles/{article_id}/evidence")
def article_evidence(article_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    a = _article(db, article_id)
    claims = list(db.scalars(select(EvidenceClaim).where(EvidenceClaim.article_id == a.id)))
    by_source: dict[uuid.UUID, dict[str, Any]] = {}
    for c in claims:
        src = db.get(EvidenceSource, c.source_id)
        entry = by_source.setdefault(src.id, {
            "id": str(src.id), "key": src.key, "url": src.url, "title": src.title, "publisher": src.publisher,
            "source_type": src.source_type, "source_class": src.source_class, "retrieval_mode": src.retrieval_mode,
            "retrieved_at": src.retrieved_at.isoformat(), "published_at": src.published_at, "snippet": src.snippet,
            "content_hash": src.content_hash, "live_status": src.live_status, "claims": [],
        })
        entry["claims"].append({"key": c.claim_key, "claim": c.claim_text, "claim_type": c.claim_type,
                                "confidence": c.confidence, "verification_status": c.verification_status})
    brief_gaps: list[str] = []
    if a.versions and a.versions[-1].brief:
        from packages.contracts.flow import ContentBrief
        from workers.research.activities import build_bundle

        try:
            brief_gaps = build_bundle(ContentBrief.model_validate(a.versions[-1].brief)).gaps
        except Exception:  # noqa: BLE001 - legacy/test briefs
            brief_gaps = []
    return {"article_id": str(a.id), "sources": list(by_source.values()), "gaps": brief_gaps,
            "note": "Evidence sources are real public documents captured as FIXTURE_SNAPSHOT; verify live before publishing."}


@router.get("/articles/{article_id}/compliance")
def article_compliance(article_id: uuid.UUID, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    a = _article(db, article_id)
    return [_decision_out(d) for d in db.scalars(select(ComplianceDecision).where(ComplianceDecision.article_id == a.id)
                                                 .order_by(ComplianceDecision.created_at.desc()))]


@router.post("/articles/{article_id}/validate")
def validate(article_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    a = _article(db, article_id)
    if a.origin != "GENERATED":
        raise Conflict("Only generated articles are validated")
    report = evaluate_article(db, a)
    d = apply_report(db, a, report, actor="policy-engine (manual re-validation)")
    ledger_for_article(db, a, "COMPLIANCE_REVALIDATED", "COMPLETED", note="Manual re-validation")
    db.flush()
    return _decision_out(d)


@router.post("/articles/{article_id}/approve")
def approve(article_id: uuid.UUID, body: ApproveIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    a = _article(db, article_id)
    project = get_default_project(db)
    auth = (project.settings or {}).get("india_authorization_status", "UNKNOWN")
    if a.compliance_status == "BLOCK":
        raise Conflict("BLOCKED content cannot be approved - fix the violations and re-validate")
    if a.content_class == "PROMOTIONAL" and auth != "VERIFIED":
        raise Conflict(f"Promotional content cannot be approved while India authorization is {auth}")
    if a.status == "APPROVED":
        return {"article_id": str(a.id), "status": a.status, "note": "already approved"}
    latest = db.scalar(select(ComplianceDecision).where(ComplianceDecision.article_id == a.id)
                       .order_by(ComplianceDecision.created_at.desc()))
    decision = ComplianceDecision(
        project_id=a.project_id, article_id=a.id, article_version=a.current_version, status=a.compliance_status,
        publication_eligibility="ELIGIBLE_EDUCATIONAL" if a.content_class == "EDUCATIONAL" else "ELIGIBLE_PROMOTIONAL",
        content_class=a.content_class, rule_results=latest.rule_results if latest else [],
        reasons=(latest.reasons if latest else []) + [f"Human approval by {body.reviewer}: {body.note}"],
        decided_by=f"human:{body.reviewer}", reviewer_note=body.note,
    )
    db.add(decision)
    a.status = "APPROVED"
    a.publication_eligibility = decision.publication_eligibility
    audit(db, a.project_id, "HUMAN_APPROVED", f"'{a.title}' approved by {body.reviewer}", article_id=a.id,
          actor=f"human:{body.reviewer}", payload={"note": body.note, "compliance_status": a.compliance_status})
    ledger_for_article(db, a, "HUMAN_APPROVED", "COMPLETED", note=f"{body.reviewer}: {body.note}")
    db.flush()
    return {"article_id": str(a.id), "status": a.status, "publication_eligibility": a.publication_eligibility}


@router.get("/internal-links")
def internal_links(db: Session = Depends(get_db)) -> dict[str, Any]:
    p = get_default_project(db)
    arts = {a.id: a for a in db.scalars(select(Article).where(Article.project_id == p.id, Article.is_test_fixture.is_(False)))}
    links = list(db.scalars(select(InternalLink).where(InternalLink.project_id == p.id)))
    return {
        "nodes": [{"id": str(a.id), "title": a.title, "slug": a.slug, "language": a.language, "origin": a.origin,
                   "sim_day": a.sim_day, "theme": a.theme, "compliance_status": a.compliance_status} for a in arts.values()],
        "edges": [{"id": str(link.id), "source": str(link.source_article_id), "target": str(link.target_article_id),
                   "anchor_text": link.anchor_text, "score": link.score, "reason": link.reason,
                   "direction": link.direction, "status": link.status}
                  for link in links if link.source_article_id in arts and link.target_article_id in arts],
    }


@router.get("/compliance/rules")
def compliance_rules() -> list[dict[str, Any]]:
    return rule_catalog()


@router.get("/compliance/decisions")
def compliance_decisions(db: Session = Depends(get_db), limit: int = 100) -> list[dict[str, Any]]:
    p = get_default_project(db)
    out = []
    for d in db.scalars(select(ComplianceDecision).where(ComplianceDecision.project_id == p.id)
                        .order_by(ComplianceDecision.created_at.desc()).limit(min(limit, 500))):
        item = _decision_out(d)
        art = db.get(Article, d.article_id) if d.article_id else None
        item["article"] = {"title": art.title, "slug": art.slug, "language": art.language,
                           "is_test_fixture": art.is_test_fixture} if art else None
        out.append(item)
    return out


@router.post("/compliance/check")
def compliance_sandbox(body: ComplianceCheckIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Run the deterministic policy engine on arbitrary text (nothing is stored)."""
    p = get_default_project(db)
    registry = FixtureEvidenceProvider().all()
    try:
        ctype = ContentType(body.content_type)
    except ValueError:
        ctype = ContentType.GUIDE
    report = run_compliance(ComplianceInput(
        markdown=body.markdown, language=Language(body.language), content_class=ContentClass(body.content_class),
        content_type=ctype, authorization_status=AuthorizationStatus((p.settings or {}).get("india_authorization_status", "UNKNOWN")),
        evidence_urls={e.url for e in registry}, evidence_status={}, other_articles={},
    ))
    return report.model_dump(mode="json")
