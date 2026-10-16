"""Content worker: ContentBrief -> ArticleDraft (LLM/demo provider + renderer) -> stored versioned article."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from temporalio import activity

from packages.config import ROOT_DIR, get_settings
from packages.contracts.enums import ContentClass, ContentType, Language, SearchIntent, Theme
from packages.contracts.flow import ContentBrief, LLMArticlePayload
from packages.domain.briefs import build_brief
from packages.domain.embedding import get_embedder
from packages.domain.linking import REVERSE_THRESHOLD, LinkTarget, suggest_links
from packages.domain.renderer import render_article
from packages.domain.seo import article_path, build_seo
from packages.persistence.db import session_scope
from packages.persistence.models import (
    Article,
    ArticleVersion,
    ContentBriefRow,
    EvidenceClaim,
    EvidenceSource,
    IntentReservation,
    InternalLink,
    KeywordCandidateRow,
    OpportunityRow,
    Project,
    WorkflowRun,
)
from packages.persistence.repositories import audit, get_run, mark_run, step
from packages.persistence.seed import article_tokens
from packages.providers.base import GenerationContext, LLMOutputError, ProviderUnavailable
from packages.providers.fixtures import content_library
from packages.providers.llm import DemoLLMProvider, get_llm_provider
from workers.research.activities import build_bundle


def _uuid(v: str | uuid.UUID) -> uuid.UUID:
    return v if isinstance(v, uuid.UUID) else uuid.UUID(v)


def link_targets(s, project_id: uuid.UUID, exclude: set[uuid.UUID] | None = None) -> list[LinkTarget]:
    out = []
    for a in s.scalars(select(Article).where(Article.project_id == project_id, Article.is_test_fixture.is_(False),
                                             Article.status != "BLOCKED")):
        if exclude and a.id in exclude:
            continue
        out.append(LinkTarget(id=a.id, slug=a.slug, title=a.title, path=article_path(a.language, a.slug), theme=a.theme,
                              intent_key=a.intent_key, entity_keys=a.entity_keys or [], language=a.language,
                              embedding=list(a.embedding) if a.embedding is not None else None, origin=a.origin))
    return out


@activity.defn(name="create_article_run")
def create_article_run(parent_run_id: str, opportunity_id: str) -> str:
    with session_scope() as s:
        parent = get_run(s, parent_run_id)
        opp = s.get(OpportunityRow, _uuid(opportunity_id))
        existing = s.scalar(select(WorkflowRun).where(WorkflowRun.parent_run_id == parent.id,
                                                      WorkflowRun.kind == "ARTICLE_GENERATION",
                                                      WorkflowRun.stats["opportunity_id"].astext == opportunity_id))
        if existing:
            return str(existing.id)
        child = WorkflowRun(project_id=parent.project_id, parent_run_id=parent.id, kind="ARTICLE_GENERATION",
                            sim_day=parent.sim_day, plan_date=parent.plan_date, status="RUNNING",
                            orchestrator=parent.orchestrator, provider_mode=parent.provider_mode, trigger="workflow",
                            started_at=datetime.now(UTC), stats={"opportunity_id": opportunity_id, "keyword": opp.keyword})
        s.add(child)
        s.flush()
        return str(child.id)


@activity.defn(name="plan_brief")
def plan_brief(article_run_id: str, opportunity_id: str) -> dict[str, Any]:
    with session_scope() as s:
        run = get_run(s, article_run_id)
        with step(s, run.id, "plan_brief") as d:
            opp = s.get(OpportunityRow, _uuid(opportunity_id))
            row = s.scalar(select(ContentBriefRow).where(ContentBriefRow.opportunity_id == opp.id))
            if row:
                d.update(skipped=True, brief_id=str(row.id))
                return d
            project = s.get(Project, opp.project_id)
            cand = s.get(KeywordCandidateRow, opp.candidate_id)
            siblings = [c.display_query for c in s.scalars(select(KeywordCandidateRow).where(
                KeywordCandidateRow.project_id == opp.project_id, KeywordCandidateRow.intent_key == opp.intent_key,
                KeywordCandidateRow.id != cand.id))]
            links = suggest_links(opp.theme, cand.entity_keys, opp.language,
                                  list(cand.embedding) if cand.embedding is not None else None,
                                  link_targets(s, opp.project_id))
            brief = build_brief(
                keyword=opp.keyword, secondary=siblings, language=Language(opp.language), locale=opp.locale,
                theme=Theme(opp.theme), intent=SearchIntent(opp.intent), content_type=ContentType(opp.content_type),
                content_class=ContentClass(opp.content_class), intent_key=opp.intent_key, entity_keys=cand.entity_keys,
                library_doc=content_library().get(opp.intent_key), internal_links=links,
                serp_gaps=(opp.serp_analysis or {}).get("content_gaps", []),
                authorization_status=(project.settings or {}).get("india_authorization_status", "UNKNOWN"),
                cta_policy=(project.settings or {}).get("cta_policy", "Educational CTA only"),
            )
            row = ContentBriefRow(project_id=opp.project_id, opportunity_id=opp.id, brief=brief.model_dump(mode="json"))
            s.add(row)
            s.flush()
            d.update(brief_id=str(row.id), title=brief.recommended_title, slug=brief.slug,
                     internal_link_suggestions=len(links), secondary_keywords=brief.secondary_keywords)
            return d


def _generate_payload(brief: ContentBrief, ctx: GenerationContext) -> tuple[LLMArticlePayload, str, list[str]]:
    """Primary provider with validated output; deterministic fallback on failure."""
    provider = get_llm_provider()
    notes: list[str] = []
    try:
        return provider.generate_article(brief, ctx), provider.name, notes
    except (LLMOutputError, ProviderUnavailable) as exc:
        notes.append(f"LLM_FALLBACK: {provider.name} failed ({type(exc).__name__}: {str(exc)[:200]}); used demo provider")
        demo = DemoLLMProvider()
        return demo.generate_article(brief, ctx), demo.name + " (fallback)", notes


def store_article(
    s, *, project: Project, opp: OpportunityRow | None, run: WorkflowRun, brief: ContentBrief, payload: LLMArticlePayload,
    generator: str, library_doc: dict[str, Any] | None, is_test: bool = False, notes: list[str] | None = None,
) -> Article:
    settings = get_settings()
    embedder = get_embedder()
    evidence_items = {i.key: i for i in build_bundle(brief).items}
    article_id = uuid.uuid4()
    targets = {t.intent_key: t for t in link_targets(s, project.id)}

    def resolve(intent_key: str) -> tuple[str, str] | None:
        t = targets.get(intent_key)
        return (t.path, t.slug) if t and not is_test else None

    related = [] if is_test else brief.internal_links
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    frontmatter = {
        "title": payload.title, "slug": brief.slug, "description": payload.meta_description,
        "keyword": brief.target_keyword, "intent": brief.search_intent.value, "intent_key": brief.intent_key,
        "language": brief.language.value, "locale": brief.locale, "hreflang": brief.hreflang,
        "content_type": brief.content_type.value, "content_class": brief.content_class.value,
        "generated_at": generated_at, "article_id": str(article_id), "version": 1,
        "compliance_status": "PENDING", "generator": generator,
        "data_label": "DEMO: search signals SIMULATED; evidence = snapshots of real public documents (verify live)",
    }
    rendered = render_article(
        payload=payload, language=brief.language.value, frontmatter=frontmatter, evidence=evidence_items,
        resolve_link=resolve, related=related,
        related_path=lambda r: next((t.path for t in targets.values() if t.id == r.target_article_id), "#"),
        table_after=(library_doc or {}).get("table", {}).get("after_section") if library_doc and library_doc.get("table") else None,
        inject_policy=not (library_doc or {}).get("skip_policy_injection", False),
        extra_sources={f["key"]: f for f in (library_doc or {}).get("fake_sources", [])},
        retrieved_label="; captured 2026-10-16",
    )
    seo = build_seo(
        title=payload.title, meta_description=payload.meta_description, h1=payload.h1, slug=brief.slug,
        language=brief.language.value, locale=brief.locale, hreflang=brief.hreflang, domain=project.domain,
        faq=[f.model_dump() for f in payload.faq], generated_at=generated_at, intent_key=brief.intent_key,
        schema_types=brief.schema_recommendations,
    )
    tokens = article_tokens(brief.target_keyword, payload.title)
    article = Article(
        id=article_id, project_id=project.id, opportunity_id=opp.id if opp else None, run_id=run.parent_run_id or run.id,
        origin="GENERATED", sim_day=run.sim_day, slug=brief.slug, title=payload.title, target_keyword=brief.target_keyword,
        language=brief.language.value, locale=brief.locale, theme=brief.theme.value, intent=brief.search_intent.value,
        intent_key=brief.intent_key if not is_test else f"redteam:{brief.intent_key}",
        entity_keys=brief.entity_keys, content_type=brief.content_type.value, content_class=brief.content_class.value,
        status="DRAFT", compliance_status="PENDING", publication_eligibility="REQUIRES_HUMAN_REVIEW", current_version=1,
        opportunity_score=opp.score if opp else None, is_test_fixture=is_test, embedding=embedder.embed(tokens),
    )
    out_dir = settings.output_path / (f"day-{run.sim_day}" if run.sim_day else "live")
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"{brief.slug}.md"
    file_path.write_text(rendered.markdown, encoding="utf-8")
    rel = file_path.relative_to(ROOT_DIR) if file_path.is_relative_to(ROOT_DIR) else file_path
    article.file_path = str(rel).replace("\\", "/")
    article.versions.append(ArticleVersion(
        version=1, markdown=rendered.markdown, frontmatter=frontmatter, seo=seo, payload=payload.model_dump(mode="json"),
        brief=brief.model_dump(mode="json"), word_count=rendered.word_count,
        content_hash=hashlib.sha256(rendered.markdown.encode()).hexdigest(), generator=generator,
        change_note="Initial draft" + (f"; {'; '.join(notes)}" if notes else ""),
    ))
    s.add(article)
    s.flush()

    # Evidence claims actually used by this article
    for key in rendered.used_evidence_keys:
        item = evidence_items[key]
        src = s.scalar(select(EvidenceSource).where(EvidenceSource.project_id == project.id, EvidenceSource.url == item.url))
        if src is None:
            src = EvidenceSource(project_id=project.id, key=item.key, url=item.url, title=item.title, publisher=item.publisher,
                                 source_type=item.source_type.value, source_class=item.source_class.value,
                                 retrieval_mode=item.retrieval_mode.value, retrieved_at=item.retrieved_at,
                                 published_at=item.published_at, snippet=item.snippet,
                                 content_hash=hashlib.sha256(item.snippet.encode()).hexdigest(), live_status={})
            s.add(src)
            s.flush()
        for c in item.claims:
            s.add(EvidenceClaim(project_id=project.id, source_id=src.id, article_id=article.id, claim_key=c.key,
                                claim_text=c.claim, claim_type=c.claim_type, confidence=c.confidence,
                                verification_status=c.verification_status.value))

    # Internal links: inline (resolved placeholders) + related-guide module
    seen: set[uuid.UUID] = set()
    for intent_key, _slug, anchor in rendered.inline_links:
        t = targets.get(intent_key)
        if t and t.id not in seen:
            seen.add(t.id)
            sug = next((r for r in related if r.target_article_id == t.id), None)
            s.add(InternalLink(project_id=project.id, source_article_id=article.id, target_article_id=t.id,
                               anchor_text=anchor, score=sug.score if sug else 0.5,
                               reason=(sug.reason if sug else f"contextual link to intent {intent_key}"), direction="INSERTED"))
    for r in related:
        if r.target_article_id not in seen:
            seen.add(r.target_article_id)
            s.add(InternalLink(project_id=project.id, source_article_id=article.id, target_article_id=r.target_article_id,
                               anchor_text=r.anchor_text, score=r.score, reason=r.reason, direction="RELATED_MODULE"))
    # Reverse suggestions: earlier relevant generated articles should link back to the new one
    if not is_test:
        for t in link_targets(s, project.id, exclude={article.id}):
            if t.origin != "GENERATED":
                continue
            back = suggest_links(t.theme, t.entity_keys, t.language, t.embedding, [LinkTarget(
                id=article.id, slug=article.slug, title=article.title, path=article_path(article.language, article.slug),
                theme=article.theme, intent_key=article.intent_key, entity_keys=article.entity_keys, language=article.language,
                embedding=list(article.embedding), origin="GENERATED")])
            if back and back[0].score >= REVERSE_THRESHOLD and not s.scalar(select(InternalLink).where(InternalLink.source_article_id == t.id,
                                                                InternalLink.target_article_id == article.id)):
                s.add(InternalLink(project_id=project.id, source_article_id=t.id, target_article_id=article.id,
                                   anchor_text=article.title, score=back[0].score,
                                   reason="Reverse suggestion: add link on next refresh of earlier article; " + back[0].reason,
                                   direction="REVERSE_SUGGESTED", status="SUGGESTED"))
    audit(s, project.id, "ARTICLE_DRAFTED",
          f"Drafted '{payload.title}' ({brief.language.value}) with {len(rendered.used_evidence_keys)} sources, "
          f"{len(rendered.inline_links)} inline links",
          run_id=run.parent_run_id or run.id, article_id=article.id,
          payload={"generator": generator, "dropped_citations": rendered.dropped_citations,
                   "unresolved_links": rendered.unresolved_links, "notes": notes or []})
    for n in notes or []:
        audit(s, project.id, "LLM_FALLBACK", n, run_id=run.parent_run_id or run.id, article_id=article.id)
    return article


@activity.defn(name="generate_article")
def generate_article(article_run_id: str, opportunity_id: str) -> dict[str, Any]:
    with session_scope() as s:
        run = get_run(s, article_run_id)
        with step(s, run.id, "generate_article") as d:
            opp = s.get(OpportunityRow, _uuid(opportunity_id))
            if opp.article_id:
                d.update(skipped=True, article_id=str(opp.article_id))
                return d
            project = s.get(Project, opp.project_id)
            brief = ContentBrief.model_validate(
                s.scalar(select(ContentBriefRow).where(ContentBriefRow.opportunity_id == opp.id)).brief)
            bundle = build_bundle(brief)
            ctx = GenerationContext(
                evidence=bundle.items,
                internal_link_targets=[{"intent_key": t.intent_key, "title": t.title, "slug": t.slug}
                                       for t in link_targets(s, project.id)],
                plan_date=run.plan_date or "",
            )
            payload, generator, notes = _generate_payload(brief, ctx)
            article = store_article(s, project=project, opp=opp, run=run, brief=brief, payload=payload,
                                    generator=generator, library_doc=content_library().get(brief.intent_key), notes=notes)
            opp.article_id = article.id
            res = s.scalar(select(IntentReservation).where(IntentReservation.project_id == project.id,
                                                           IntentReservation.intent_key == opp.intent_key))
            if res:
                res.article_id = article.id
            run.stats = {**(run.stats or {}), "article_id": str(article.id)}
            d.update(article_id=str(article.id), slug=article.slug, generator=generator, notes=notes,
                     words=article.versions[0].word_count)
            return d


@activity.defn(name="generate_redteam")
def generate_redteam(run_id: str) -> dict[str, Any]:
    """Push the intentionally unsafe fixture through the same pipeline to prove the gate blocks it."""
    with session_scope() as s:
        run = get_run(s, run_id)
        with step(s, run.id, "redteam_compliance_probe") as d:
            doc = content_library().get("bonus:exness")
            existing = s.scalar(select(Article).where(Article.project_id == run.project_id, Article.slug == doc["slug"]))
            if existing:
                d.update(skipped=True, article_id=str(existing.id))
                return d
            project = s.get(Project, run.project_id)
            brief = build_brief(
                keyword="exness bonus", secondary=[], language=Language.EN, locale="en-IN", theme=Theme.BONUS,
                intent=SearchIntent.TRANSACTIONAL, content_type=ContentType.PROMOTIONAL, content_class=ContentClass.PROMOTIONAL,
                intent_key="bonus:exness", entity_keys=["exness"], library_doc=doc, internal_links=[], serp_gaps=[],
                authorization_status=(project.settings or {}).get("india_authorization_status", "UNKNOWN"),
                cta_policy="RED-TEAM FIXTURE",
            )
            payload = DemoLLMProvider().generate_article(brief, GenerationContext(evidence=[], internal_link_targets=[], plan_date=""))
            article = store_article(s, project=project, opp=None, run=run, brief=brief, payload=payload,
                                    generator="adversarial-test-fixture", library_doc=doc, is_test=True)
            audit(s, project.id, "REDTEAM_PROBE",
                  "Injected ADVERSARIAL TEST FIXTURE (unsafe promotional draft) to verify the compliance gate",
                  run_id=run.id, article_id=article.id)
            d.update(article_id=str(article.id), slug=article.slug)
            return d


@activity.defn(name="complete_article_run")
def complete_article_run(article_run_id: str, ok: bool, error: str = "") -> None:
    with session_scope() as s:
        run = get_run(s, article_run_id)
        mark_run(s, run, "COMPLETED" if ok else "FAILED", error=error or None)
