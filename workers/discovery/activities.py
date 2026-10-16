"""Discovery worker: expand seeds -> observe (suggest/trends/news) -> normalise into candidates/clusters."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio import activity

from packages.config import get_settings
from packages.contracts.enums import Language, SourceType
from packages.contracts.flow import SearchObservation
from packages.domain.discovery import expand_seeds, rotate_seeds
from packages.domain.embedding import get_embedder
from packages.domain.language import analyze_query, normalize_query
from packages.persistence.db import session_scope
from packages.persistence.models import (
    BrokerDemandSnapshot,
    Entity,
    IntentCluster,
    KeywordCandidateRow,
    SearchObservationRow,
)
from packages.persistence.repositories import audit, get_run, step
from packages.providers.base import ProviderUnavailable
from packages.providers.fixtures import day_config
from packages.providers.signals import measure_broker_demand, simulated_broker_demand
from workers.common import run_context, suggestion_providers, trend_providers


@activity.defn(name="discover")
def discover(run_id: str) -> dict[str, Any]:
    with session_scope() as s:
        run = get_run(s, run_id)
        ctx = run_context(s, run)
        with step(s, run.id, "discover") as d:
            existing = s.scalars(select(SearchObservationRow.id).where(SearchObservationRow.run_id == run.id)).first()
            if existing:
                d.update(skipped=True, reason="observations already stored for this run (idempotent replay)")
                return d
            brokers = _tracked_brokers(s, ctx.project.id)
            languages = [Language(lang) for lang in ctx.settings.get("languages", ["en", "hi", "hi-Latn"])]
            seeds = expand_seeds(brokers, languages)
            all_seeds = len(seeds)
            if not ctx.is_simulated:
                seeds = rotate_seeds(seeds, get_settings().autocomplete_budget, ctx.plan_date.toordinal())
            collected: dict[tuple[str, str], SearchObservation] = {}
            failures: list[str] = []
            for provider in suggestion_providers(ctx):
                for seed in seeds:
                    try:
                        for obs in provider.suggest(seed, ctx.sim_day):
                            key = (normalize_query(obs.query), obs.language.value)
                            if key not in collected or (obs.demand_proxy or 0) > (collected[key].demand_proxy or 0):
                                collected[key] = obs
                    except ProviderUnavailable as exc:
                        failures.append(f"{provider.name}: {exc}")
                        break  # provider down -> stop hammering it, continue with others
            for provider in trend_providers(ctx, brokers):
                try:
                    for obs in provider.rising(ctx.sim_day, languages):
                        collected[(normalize_query(obs.query), obs.language.value)] = obs
                except ProviderUnavailable as exc:
                    failures.append(f"{provider.name}: {exc}")
            for obs in collected.values():
                s.add(SearchObservationRow(
                    project_id=ctx.project.id, run_id=run.id, sim_day=ctx.sim_day, query=obs.query,
                    normalized_query=normalize_query(obs.query), language=obs.language.value, locale=obs.locale,
                    source=obs.source, source_type=obs.source_type.value, confidence=obs.confidence,
                    demand_proxy=obs.demand_proxy, trend_velocity=obs.trend_velocity, seed=obs.seed,
                    entity_keys=obs.entity_keys, is_news=obs.is_news, observed_at=obs.observed_at, raw=obs.raw,
                ))
            by_lang: dict[str, int] = {}
            by_source: dict[str, int] = {}
            for o in collected.values():
                by_lang[o.language.value] = by_lang.get(o.language.value, 0) + 1
                by_source[o.source] = by_source.get(o.source, 0) + 1
            d.update(seeds_expanded=all_seeds, seeds_queried=len(seeds), observations=len(collected), by_language=by_lang, by_source=by_source,
                     provider_failures=failures, data_label="SIMULATED" if ctx.is_simulated else "REAL_PUBLIC")
            audit(s, ctx.project.id, "DISCOVERY_COMPLETED",
                  f"Expanded {len(seeds)} seed queries across {len(languages)} languages; stored {len(collected)} observations",
                  run_id=run.id, payload=d)
            return d


def _tracked_brokers(s: Session, project_id: uuid.UUID) -> dict[str, str]:
    return {e.key: e.name for e in s.scalars(
        select(Entity).where(Entity.project_id == project_id, Entity.kind == "BROKER", Entity.tracked.is_(True)))}


@activity.defn(name="track_brokers")
def track_brokers(run_id: str) -> dict[str, Any]:
    """Broker demand leaderboard for the day: which brokers do Indian searchers care about right now?

    Live: autocomplete depth + category share + 7-day news count (PROXY). Demo: aggregated fixture demand (SIMULATED).
    Untracked brokers that surface in category autocompletes are recorded as discoveries."""
    with session_scope() as s:
        run = get_run(s, run_id)
        ctx = run_context(s, run)
        with step(s, run.id, "track_brokers") as d:
            if s.scalars(select(BrokerDemandSnapshot.id).where(BrokerDemandSnapshot.run_id == run.id)).first():
                d.update(skipped=True, reason="broker demand already stored for this run (idempotent replay)")
                return d
            tracked = _tracked_brokers(s, ctx.project.id)
            failures: list[str] = []
            if ctx.is_simulated:
                cfg = day_config(ctx.sim_day)
                ranked = simulated_broker_demand(tracked, cfg["observations"], cfg["date"])
            elif get_settings().live_broker_demand:
                ranked, failures = measure_broker_demand(tracked)
            else:
                d.update(skipped=True, reason="ATLAS_LIVE_BROKER_DEMAND=false")
                return d
            for rank, b in enumerate(ranked, start=1):
                s.add(BrokerDemandSnapshot(
                    project_id=ctx.project.id, run_id=run.id, captured_on=ctx.plan_date.isoformat(), entity_key=b.entity_key,
                    name=b.name, demand_index=b.index, rank=rank, tracked=b.tracked, source_type=b.source_type,
                    components=b.components))
            discovered = [b.name for b in ranked if not b.tracked and b.index > 0]
            d.update(brokers_ranked=len(ranked), top=[f"{b.name} {b.index:.0f}" for b in ranked[:5]],
                     discovered_untracked=discovered, provider_failures=failures,
                     data_label="SIMULATED" if ctx.is_simulated else "PROXY (public autocomplete + news; no volumes)")
            audit(s, ctx.project.id, "BROKER_DEMAND_TRACKED",
                  f"Ranked {len(ranked)} brokers; top: {', '.join(d['top'][:3]) or 'none'}"
                  + (f"; new in demand: {', '.join(discovered)}" if discovered else ""), run_id=run.id, payload=d)
            return d


@activity.defn(name="normalize")
def normalize(run_id: str) -> dict[str, Any]:
    embedder = get_embedder()
    with session_scope() as s:
        run = get_run(s, run_id)
        ctx = run_context(s, run)
        with step(s, run.id, "normalize") as d:
            rows = list(s.scalars(select(SearchObservationRow).where(SearchObservationRow.run_id == run.id)))
            touched: set[str] = set()
            new_today = 0
            for o in rows:
                a = analyze_query(o.query)
                cand = s.scalar(select(KeywordCandidateRow).where(
                    KeywordCandidateRow.project_id == ctx.project.id,
                    KeywordCandidateRow.normalized_query == a.normalized,
                    KeywordCandidateRow.language == a.language.value))
                cluster = s.scalar(select(IntentCluster).where(
                    IntentCluster.project_id == ctx.project.id, IntentCluster.intent_key == a.intent_key))
                if cluster is None:
                    cluster = IntentCluster(project_id=ctx.project.id, intent_key=a.intent_key, label=o.query,
                                            theme=a.theme.value, intent=a.intent.value, entity_keys=a.entity_keys,
                                            languages=[a.language.value], candidate_count=0)
                    s.add(cluster)
                    s.flush()
                if a.language.value not in (cluster.languages or []):
                    cluster.languages = [*cluster.languages, a.language.value]
                if cand is None:
                    cand = KeywordCandidateRow(
                        project_id=ctx.project.id, cluster_id=cluster.id, normalized_query=a.normalized,
                        display_query=o.query, language=a.language.value, locale=a.locale, theme=a.theme.value,
                        intent=a.intent.value, entity_keys=a.entity_keys, intent_key=a.intent_key,
                        concept_tokens=a.concept_tokens, demand_proxy=o.demand_proxy, trend_velocity=o.trend_velocity,
                        source_types=[o.source_type], observation_count=1, is_news=o.is_news,
                        first_seen_day=ctx.sim_day, last_seen_day=ctx.sim_day, embedding=embedder.embed(a.concept_tokens),
                    )
                    s.add(cand)
                    cluster.candidate_count += 1
                    new_today += 1
                else:
                    cand.demand_proxy = o.demand_proxy
                    cand.trend_velocity = o.trend_velocity
                    cand.observation_count += 1
                    cand.last_seen_day = ctx.sim_day
                    cand.is_news = cand.is_news or o.is_news
                    if o.source_type not in cand.source_types:
                        cand.source_types = [*cand.source_types, o.source_type]
                    if len(o.query) > len(cand.display_query):
                        cand.display_query = o.query
                touched.add(f"{a.normalized}|{a.language.value}")
            d.update(candidates_touched=len(touched), new_candidates=new_today,
                     simulated=all(r.source_type == SourceType.SIMULATED.value for r in rows))
            return d
