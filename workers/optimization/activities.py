"""Optimization worker: score -> cannibalization -> select -> reserve intents (DB-enforced) -> plan."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from temporalio import activity

from packages.config import get_settings
from packages.contracts.enums import (
    CannibalizationDecision,
    OpportunityStatus,
    SearchIntent,
    SourceType,
    Theme,
)
from packages.contracts.flow import KeywordCandidate, SerpAnalysis
from packages.domain.briefs import ascii_slug
from packages.domain.cannibalization import CandidateView, InventoryItem, evaluate
from packages.domain.scoring import content_class_for, content_type_for, score_candidate
from packages.persistence.db import session_scope
from packages.persistence.models import (
    Article,
    ContentPlanRow,
    IntentReservation,
    OpportunityRow,
    SerpSnapshotRow,
)
from packages.persistence.repositories import audit, get_run, ledger, step
from packages.persistence.seed import article_tokens
from packages.providers.fixtures import content_library
from workers.common import run_context
from workers.research.activities import run_candidates

DECISION_TO_STATUS = {
    CannibalizationDecision.REJECT_NEW_PAGE: OpportunityStatus.REJECTED,
    CannibalizationDecision.UPDATE_EXISTING_PAGE: OpportunityStatus.UPDATE_EXISTING,
    CannibalizationDecision.LOCALE_VARIANT: OpportunityStatus.LOCALE_VARIANT,
}


def proposed_slug(intent_key: str, query: str) -> str:
    doc = content_library().get(intent_key)
    return doc["slug"] if doc else ascii_slug(query)


def inventory_items(s, project_id) -> list[InventoryItem]:
    items: list[InventoryItem] = []
    serp_by_opp: dict[Any, set[str]] = {}
    for a in s.scalars(select(Article).where(Article.project_id == project_id, Article.is_test_fixture.is_(False))):
        urls: set[str] = set()
        if a.opportunity_id:
            opp = s.get(OpportunityRow, a.opportunity_id)
            if opp:
                snap = s.scalar(select(SerpSnapshotRow).where(SerpSnapshotRow.candidate_id == opp.candidate_id)
                                .order_by(SerpSnapshotRow.captured_at.desc()))
                urls = {r["url"] for r in (snap.results if snap else [])}
        serp_by_opp[a.id] = urls
        items.append(InventoryItem(
            kind="article", id=a.id, label=f"{a.title} [{a.origin}, {a.language}]", intent_key=a.intent_key,
            theme=a.theme, language=a.language, entity_keys=a.entity_keys or [],
            concept_tokens=article_tokens(a.target_keyword, a.title),
            embedding=list(a.embedding) if a.embedding is not None else None, slug=a.slug, serp_urls=urls,
            blocked=a.status == "BLOCKED",
        ))
    return items


def to_contract(c, sim_day) -> KeywordCandidate:
    return KeywordCandidate(
        normalized_query=c.normalized_query, display_query=c.display_query, language=c.language, locale=c.locale,
        theme=Theme(c.theme), intent=SearchIntent(c.intent), entity_keys=c.entity_keys, intent_key=c.intent_key,
        concept_tokens=c.concept_tokens, demand_proxy=c.demand_proxy, trend_velocity=c.trend_velocity,
        source_types=[SourceType(x) for x in c.source_types], observation_count=c.observation_count,
        is_news=c.is_news, is_new_today=(sim_day is not None and c.first_seen_day == sim_day),
    )


@activity.defn(name="score_and_select")
def score_and_select(run_id: str) -> dict[str, Any]:
    settings = get_settings()
    with session_scope() as s:
        run = get_run(s, run_id)
        ctx = run_context(s, run)
        with step(s, run.id, "score_and_select") as d:
            existing = list(s.scalars(select(OpportunityRow).where(OpportunityRow.run_id == run.id)))
            if existing:
                sel = [o for o in existing if o.status == OpportunityStatus.SELECTED.value]
                sel.sort(key=lambda o: o.rank or 0)
                d.update(skipped=True, selected=[str(o.id) for o in sel])
                return d

            inventory = inventory_items(s, ctx.project.id)
            reserved = {r.intent_key for r in s.scalars(select(IntentReservation).where(IntentReservation.project_id == ctx.project.id))}
            snaps = {r.candidate_id: r for r in s.scalars(select(SerpSnapshotRow).where(SerpSnapshotRow.run_id == run.id))}
            scored = []
            for c in run_candidates(s, run):
                kc = to_contract(c, ctx.sim_day)
                snap = snaps.get(c.id)
                serp = SerpAnalysis.model_validate(snap.analysis) if snap else None
                view = CandidateView(
                    intent_key=c.intent_key, theme=c.theme, language=c.language, entity_keys=c.entity_keys,
                    concept_tokens=c.concept_tokens, embedding=list(c.embedding) if c.embedding is not None else None,
                    slug=proposed_slug(c.intent_key, c.display_query),
                    serp_urls={r["url"] for r in (snap.results if snap else [])},
                )
                result, max_sim, penalty = evaluate(view, inventory)
                soft_penalty = penalty if result.decision == CannibalizationDecision.NEW_PAGE_OK else 0.0
                score, comps, why = score_candidate(kc, serp, max_sim, soft_penalty)
                scored.append({"c": c, "kc": kc, "view": view, "serp": serp, "score": score, "comps": comps, "why": why, "result": result})

            scored.sort(key=lambda x: -x["score"])
            threshold = settings.selection_threshold
            selected: list[OpportunityRow] = []
            planned_items: list[InventoryItem] = []
            rows: list[OpportunityRow] = []
            for rank, item in enumerate(scored, start=1):
                c = item["c"]
                # Re-evaluate against articles AND opportunities already selected today
                result, _, _ = evaluate(item["view"], inventory + planned_items)
                ctype = content_type_for(item["kc"].theme, item["kc"].intent)
                cclass = content_class_for(ctype)
                status, reason = OpportunityStatus.CANDIDATE, ""
                if result.decision != CannibalizationDecision.NEW_PAGE_OK:
                    status, reason = DECISION_TO_STATUS[result.decision], result.reason
                elif c.intent_key in reserved:
                    status, reason = OpportunityStatus.REJECTED, f"Intent '{c.intent_key}' already reserved (previous run)"
                elif item["score"] < threshold and not (len(selected) < settings.min_pages_per_day and item["score"] >= threshold - 10):
                    status, reason = OpportunityStatus.REJECTED, f"Score {item['score']:.1f} below selection threshold {threshold:.0f}"
                elif len(selected) >= ctx.max_pages:
                    status, reason = OpportunityStatus.DEFERRED, f"Daily capacity reached ({ctx.max_pages} pages/day) - eligible for a later day"
                else:
                    status, reason = OpportunityStatus.SELECTED, "Highest-scoring unique intent with no cannibalization conflict"

                opp = OpportunityRow(
                    project_id=ctx.project.id, run_id=run.id, candidate_id=c.id, sim_day=ctx.sim_day,
                    intent_key=c.intent_key, keyword=c.display_query, language=c.language, locale=c.locale,
                    theme=c.theme, intent=c.intent, content_type=ctype.value, content_class=cclass.value,
                    score=item["score"], components=[x.model_dump(mode="json") for x in item["comps"]], why=item["why"],
                    serp_analysis=item["serp"].model_dump(mode="json") if item["serp"] else {}, status=status.value,
                    status_reason=reason, cannibalization=result.model_dump(mode="json"),
                    conflicting_article_id=result.conflicting_article_id, rank=rank,
                )
                s.add(opp)
                s.flush()
                if status == OpportunityStatus.SELECTED:
                    # Database-enforced uniqueness: concurrent runs cannot both reserve the intent.
                    try:
                        with s.begin_nested():
                            s.add(IntentReservation(project_id=ctx.project.id, intent_key=c.intent_key, opportunity_id=opp.id, run_id=run.id))
                    except IntegrityError:
                        opp.status = OpportunityStatus.REJECTED.value
                        opp.status_reason = f"Intent '{c.intent_key}' reservation rejected by database UNIQUE constraint"
                        audit(s, ctx.project.id, "INTENT_RESERVATION_CONFLICT", opp.status_reason, run_id=run.id)
                    else:
                        reserved.add(c.intent_key)
                        selected.append(opp)
                        planned_items.append(InventoryItem(
                            kind="opportunity", id=opp.id, label=f"{c.display_query} [selected today, {c.language}]",
                            intent_key=c.intent_key, theme=c.theme, language=c.language, entity_keys=c.entity_keys,
                            concept_tokens=c.concept_tokens, embedding=item["view"].embedding, slug=item["view"].slug,
                            serp_urls=item["view"].serp_urls,
                        ))
                rows.append(opp)
                if opp.status in (OpportunityStatus.REJECTED.value, OpportunityStatus.UPDATE_EXISTING.value,
                                  OpportunityStatus.LOCALE_VARIANT.value) and not opp.status_reason.startswith("Score"):
                    ledger(s, ctx.project.id, {
                        OpportunityStatus.REJECTED.value: "OPPORTUNITY_REJECTED",
                        OpportunityStatus.UPDATE_EXISTING.value: "UPDATE_EXISTING_RECOMMENDED",
                        OpportunityStatus.LOCALE_VARIANT.value: "LOCALE_VARIANT_DEFERRED",
                    }[opp.status], plan_date=ctx.plan_date.isoformat(), sim_day=ctx.sim_day, run_id=run.id,
                        opportunity_id=opp.id, target_keyword=opp.keyword, language=opp.language, locale=opp.locale,
                        intent=opp.intent, intent_key=opp.intent_key, opportunity_score=opp.score,
                        target_slug=item["view"].slug, content_status="NOT_SCHEDULED", workflow_status=run.status,
                        note=opp.status_reason)

            plan = ContentPlanRow(
                project_id=ctx.project.id, run_id=run.id, plan_date=ctx.plan_date.isoformat(), sim_day=ctx.sim_day,
                selected_opportunity_ids=[str(o.id) for o in selected],
                rejected_opportunity_ids=[str(o.id) for o in rows if o.status != OpportunityStatus.SELECTED.value],
                rationale=[f"#{o.rank} {o.keyword} ({o.language}) score {o.score:.1f}: {', '.join(o.why[:3])}" for o in selected],
            )
            s.add(plan)
            counts: dict[str, int] = {}
            for o in rows:
                counts[o.status] = counts.get(o.status, 0) + 1
            d.update(scored=len(rows), selected=[str(o.id) for o in selected], status_counts=counts,
                     selected_keywords=[o.keyword for o in selected], threshold=threshold)
            audit(s, ctx.project.id, "CONTENT_PLAN_CREATED",
                  f"Selected {len(selected)} of {len(rows)} opportunities for {ctx.plan_date.isoformat()}",
                  run_id=run.id, payload={"counts": counts, "selected": d["selected_keywords"]})
            return d
