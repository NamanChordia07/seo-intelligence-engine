"""Research worker: SERP observation/analysis per candidate and evidence bundles per brief."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from temporalio import activity

from packages.config import get_settings
from packages.contracts.enums import Language, Theme, VerificationStatus
from packages.contracts.flow import ContentBrief, EvidenceBundle, EvidenceItem
from packages.domain.briefs import THEME_EVIDENCE_TAGS
from packages.domain.serp import analyze_serp
from packages.persistence.db import session_scope
from packages.persistence.models import (
    ContentBriefRow,
    EvidenceSource,
    KeywordCandidateRow,
    OpportunityRow,
    SearchObservationRow,
    SerpSnapshotRow,
)
from packages.persistence.repositories import audit, get_run, step
from packages.providers.base import ProviderUnavailable
from workers.common import evidence_provider, extractor, run_context, serp_provider


def run_candidates(s, run) -> list[KeywordCandidateRow]:
    keys = {(o.normalized_query, o.language) for o in s.scalars(
        select(SearchObservationRow).where(SearchObservationRow.run_id == run.id))}
    if not keys:
        return []
    cands = s.scalars(select(KeywordCandidateRow).where(KeywordCandidateRow.project_id == run.project_id))
    return [c for c in cands if (c.normalized_query, c.language) in keys]


@activity.defn(name="analyze_serps")
def analyze_serps(run_id: str) -> dict[str, Any]:
    with session_scope() as s:
        run = get_run(s, run_id)
        ctx = run_context(s, run)
        with step(s, run.id, "analyze_serps") as d:
            provider = serp_provider(ctx)
            done = {r.candidate_id for r in s.scalars(select(SerpSnapshotRow).where(SerpSnapshotRow.run_id == run.id))}
            analysed, failed = 0, []
            for c in run_candidates(s, run):
                if c.id in done:
                    continue
                try:
                    snap = provider.serp(c.display_query, Language(c.language), c.intent_key)
                except ProviderUnavailable as exc:
                    failed.append(f"{c.display_query}: {exc}")
                    continue
                analysis = analyze_serp(snap, c.concept_tokens, Theme(c.theme), ctx.plan_date)
                s.add(SerpSnapshotRow(
                    project_id=ctx.project.id, run_id=run.id, candidate_id=c.id, query=c.display_query,
                    language=c.language, source=snap.source, source_type=snap.source_type.value,
                    results=[r.model_dump(mode="json") for r in snap.results], analysis=analysis.model_dump(mode="json"),
                    captured_at=snap.captured_at,
                ))
                analysed += 1
            d.update(analysed=analysed, provider=provider.name, failures=failed,
                     note="Heuristic SERP features; not search-engine metrics")
            return d


def _worst_status(item: EvidenceItem) -> VerificationStatus:
    order = [VerificationStatus.CONFLICTING, VerificationStatus.UNVERIFIED, VerificationStatus.VERIFIED_SNAPSHOT,
             VerificationStatus.VERIFIED_LIVE]
    return min((c.verification_status for c in item.claims), key=order.index)


def build_bundle(brief: ContentBrief) -> EvidenceBundle:
    provider = evidence_provider()
    tags = THEME_EVIDENCE_TAGS.get(brief.theme, [brief.theme.value])
    items = provider.find(tags, brief.entity_keys)
    gaps: list[str] = []
    if brief.theme == Theme.COMPARISON:
        for ent in brief.entity_keys:
            register_level = [i for i in items if ent in i.tags and _worst_status(i) == VerificationStatus.VERIFIED_SNAPSHOT]
            if not register_level:
                gaps.append(f"No register-level licence evidence for '{ent}' - licence claims omitted or labelled UNVERIFIED")
        gaps.append("No primary-source spread or withdrawal-time data - numbers omitted; comparison method provided instead")
    if brief.theme == Theme.WITHDRAWAL:
        gaps.append("No verified broker-specific processing times - generic process only")
    notes = [f"{len(items)} candidate sources matched tags {tags}",
             "Snapshots of real public documents (FIXTURE_SNAPSHOT) - re-verify live before publication"]
    return EvidenceBundle(brief_intent_key=brief.intent_key, items=items, gaps=gaps, notes=notes)


@activity.defn(name="research_evidence")
def research_evidence(article_run_id: str, opportunity_id: str) -> dict[str, Any]:
    settings = get_settings()
    with session_scope() as s:
        run = get_run(s, article_run_id)
        with step(s, run.id, "research_evidence") as d:
            opp = s.get(OpportunityRow, uuid.UUID(opportunity_id))
            brief_row = s.scalar(select(ContentBriefRow).where(ContentBriefRow.opportunity_id == opp.id))
            brief = ContentBrief.model_validate(brief_row.brief)
            bundle = build_bundle(brief)
            live_checked = 0
            for item in bundle.items:
                src = s.scalar(select(EvidenceSource).where(EvidenceSource.project_id == opp.project_id, EvidenceSource.url == item.url))
                if src is None:
                    src = EvidenceSource(
                        project_id=opp.project_id, key=item.key, url=item.url, title=item.title, publisher=item.publisher,
                        source_type=item.source_type.value, source_class=item.source_class.value,
                        retrieval_mode=item.retrieval_mode.value, retrieved_at=item.retrieved_at,
                        published_at=item.published_at, snippet=item.snippet,
                        content_hash=hashlib.sha256(item.snippet.encode()).hexdigest(), live_status={},
                    )
                    s.add(src)
                if settings.live_research and not src.live_status:
                    try:
                        page = extractor().extract(item.url)
                        src.live_status = {"status": page.status, "title": page.title[:200], "error": page.error}
                    except ProviderUnavailable as exc:
                        src.live_status = {"status": None, "error": str(exc)[:300]}
                    live_checked += 1
            d.update(sources=len(bundle.items), gaps=bundle.gaps, live_checked=live_checked,
                     keys=[i.key for i in bundle.items])
            audit(s, opp.project_id, "EVIDENCE_BUNDLE_BUILT",
                  f"Evidence bundle for '{brief.target_keyword}': {len(bundle.items)} sources, {len(bundle.gaps)} gaps",
                  run_id=run.id, payload={"keys": d["keys"], "gaps": bundle.gaps})
            return d
