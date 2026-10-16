"""Compliance worker: deterministic policy engine (authoritative) + optional LLM advisory notes."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from temporalio import activity

from packages.config import ROOT_DIR, get_settings
from packages.contracts.enums import (
    AuthorizationStatus,
    CannibalizationDecision,
    ContentClass,
    ContentType,
    Language,
    VerificationStatus,
)
from packages.domain.compliance import ComplianceInput, run_compliance
from packages.domain.renderer import set_frontmatter_value
from packages.persistence.db import session_scope
from packages.persistence.models import (
    Article,
    ComplianceDecision,
    EvidenceClaim,
    EvidenceSource,
    IntentReservation,
    LedgerEntry,
    OpportunityRow,
    Project,
)
from packages.persistence.repositories import audit, get_run, ledger, step
from packages.providers.base import LLMOutputError, ProviderUnavailable
from packages.providers.llm import get_llm_provider
from packages.providers.simulated import FixtureEvidenceProvider

STATUS_TO_ARTICLE = {"PASS": "APPROVED", "REVIEW": "IN_REVIEW", "BLOCK": "BLOCKED"}
_ORDER = [VerificationStatus.CONFLICTING, VerificationStatus.UNVERIFIED, VerificationStatus.VERIFIED_SNAPSHOT,
          VerificationStatus.VERIFIED_LIVE]


def evaluate_article(s, article: Article, markdown: str | None = None):
    project = s.get(Project, article.project_id)
    version = article.versions[-1]
    md = markdown if markdown is not None else version.markdown
    registry = FixtureEvidenceProvider().all()
    # Evidence bundle URLs = sources recorded for this project (fixture registry + any live-added sources)
    urls = {e.url for e in registry} | {src.url for src in s.scalars(select(EvidenceSource).where(EvidenceSource.project_id == project.id))}
    status = {e.url: min((c.verification_status for c in e.claims), key=_ORDER.index) for e in registry}
    for c in s.scalars(select(EvidenceClaim).where(EvidenceClaim.article_id == article.id)):
        src = s.get(EvidenceSource, c.source_id)
        vs = VerificationStatus(c.verification_status)
        if src.url not in status or _ORDER.index(vs) < _ORDER.index(status[src.url]):
            status[src.url] = vs
    others = {
        f"{a.title} ({a.slug})": a.versions[-1].markdown
        for a in s.scalars(select(Article).where(Article.project_id == project.id, Article.id != article.id,
                                                 Article.is_test_fixture.is_(False)))
        if a.versions
    }
    decision = None
    reserved = True
    if article.opportunity_id:
        opp = s.get(OpportunityRow, article.opportunity_id)
        decision = CannibalizationDecision((opp.cannibalization or {}).get("decision", "NEW_PAGE_OK"))
        reserved = s.scalar(select(IntentReservation).where(IntentReservation.project_id == project.id,
                                                            IntentReservation.intent_key == article.intent_key)) is not None
    elif article.is_test_fixture:
        decision, reserved = CannibalizationDecision.NEW_PAGE_OK, True
    ci = ComplianceInput(
        markdown=md, language=Language(article.language), content_class=ContentClass(article.content_class),
        content_type=ContentType(article.content_type),
        authorization_status=AuthorizationStatus((project.settings or {}).get("india_authorization_status", "UNKNOWN")),
        evidence_urls=urls, evidence_status=status, other_articles=others, cannibalization_decision=decision,
        intent_reserved=reserved, named_entities=article.entity_keys or [],
    )
    return run_compliance(ci)


def llm_advisory(markdown: str, language: str) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.llm_advisory_review or settings.llm_provider == "demo":
        return None
    provider = get_llm_provider()
    system = ("You review financial-education articles for an Indian audience. Return JSON "
              '{"concerns": [str], "tone": "neutral|promotional|alarmist", "unsupported_claims": [str]}. Advisory only.')
    try:
        out = provider.complete_json(system, f"Language: {language}\n\n{markdown[:6000]}")
        return {"provider": provider.name, "advisory_only": True, **out}
    except (LLMOutputError, ProviderUnavailable) as exc:
        return {"provider": provider.name, "advisory_only": True, "error": str(exc)[:300]}


def apply_report(s, article: Article, report, *, run_id=None, actor="policy-engine", note: str | None = None) -> ComplianceDecision:
    version = article.versions[-1]
    advisory = llm_advisory(version.markdown, article.language)
    decision = ComplianceDecision(
        project_id=article.project_id, article_id=article.id, article_version=version.version, status=report.status.value,
        publication_eligibility=report.publication_eligibility.value, content_class=report.content_class.value,
        rule_results=[r.model_dump(mode="json") for r in report.rule_results], reasons=report.reasons,
        llm_advisory=advisory, decided_by=actor, reviewer_note=note,
    )
    s.add(decision)
    article.compliance_status = report.status.value
    human = s.scalar(select(ComplianceDecision).where(
        ComplianceDecision.article_id == article.id, ComplianceDecision.article_version == version.version,
        ComplianceDecision.decided_by.like("human:%")).order_by(ComplianceDecision.created_at.desc()))
    if human is not None and report.status.value == "REVIEW":
        # Human sign-off on this exact version stands while the deterministic outcome is unchanged (REVIEW)
        article.status = "APPROVED"
        article.publication_eligibility = human.publication_eligibility
    else:
        article.publication_eligibility = report.publication_eligibility.value
        article.status = STATUS_TO_ARTICLE[report.status.value]
    # Keep the Markdown artifact's frontmatter in sync (metadata only; body unchanged)
    md = set_frontmatter_value(version.markdown, "compliance_status", report.status.value)
    version.markdown = md
    version.frontmatter = {**version.frontmatter, "compliance_status": report.status.value}
    if article.file_path:
        path = ROOT_DIR / article.file_path
        if path.exists():
            path.write_text(md, encoding="utf-8")
    failed = [r for r in report.rule_results if not r.passed]
    audit(s, article.project_id, f"COMPLIANCE_{report.status.value}",
          f"'{article.title}' -> {report.status.value} / {report.publication_eligibility.value} "
          f"({len(failed)} rule(s) flagged)", run_id=run_id, article_id=article.id, actor=actor,
          payload={"flagged": [f"{r.rule_id}:{r.outcome}" for r in failed]})
    return decision


def ledger_for_article(s, article: Article, entry_type: str, run_status: str, run_id=None, note: str | None = None) -> None:
    sources = sorted({src.url for c in s.scalars(select(EvidenceClaim).where(EvidenceClaim.article_id == article.id))
                      for src in [s.get(EvidenceSource, c.source_id)]})
    opp = s.get(OpportunityRow, article.opportunity_id) if article.opportunity_id else None
    plan_date = None
    if article.sim_day:
        from packages.providers.fixtures import day_config

        plan_date = day_config(article.sim_day)["date"]
    ledger(s, article.project_id, entry_type, plan_date=plan_date, sim_day=article.sim_day, run_id=run_id or article.run_id,
           article_id=article.id, opportunity_id=article.opportunity_id, target_keyword=article.target_keyword,
           language=article.language, locale=article.locale, intent=article.intent, intent_key=article.intent_key,
           opportunity_score=opp.score if opp else None, target_slug=article.slug, content_status=article.status,
           compliance_status=article.compliance_status, publication_eligibility=article.publication_eligibility,
           workflow_status=run_status, evidence_sources=sources, article_version=article.current_version,
           note=note or ("ADVERSARIAL TEST FIXTURE - not a real page" if article.is_test_fixture else None))


@activity.defn(name="validate_article")
def validate_article(article_run_id: str, article_id: str) -> dict[str, Any]:
    with session_scope() as s:
        run = get_run(s, article_run_id)
        with step(s, run.id, "validate_compliance") as d:
            article = s.get(Article, uuid.UUID(article_id))
            have = s.scalar(select(ComplianceDecision).where(ComplianceDecision.article_id == article.id,
                                                             ComplianceDecision.article_version == article.current_version))
            if have:
                d.update(skipped=True, status=have.status)
                return d
            report = evaluate_article(s, article)
            parent_id = run.parent_run_id or run.id
            apply_report(s, article, report, run_id=parent_id)
            already = s.scalar(select(LedgerEntry).where(LedgerEntry.article_id == article.id,
                                                         LedgerEntry.entry_type.in_(["ARTICLE_CREATED", "REDTEAM_BLOCKED"])))
            if not already:
                ledger_for_article(s, article, "REDTEAM_BLOCKED" if article.is_test_fixture else "ARTICLE_CREATED",
                                   "COMPLETED", run_id=parent_id)
            d.update(status=report.status.value, eligibility=report.publication_eligibility.value,
                     flagged=[f"{r.rule_id} {r.name}: {r.outcome}" for r in report.rule_results if not r.passed])
            return d


def report_json(report) -> str:
    return json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
