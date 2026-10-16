"""Discovery worker: expand seeds -> observe (suggest/trends/news) -> normalise into candidates/clusters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from temporalio import activity

from packages.contracts.enums import Language, SourceType
from packages.contracts.flow import SearchObservation
from packages.domain.discovery import expand_seeds
from packages.domain.embedding import get_embedder
from packages.domain.language import analyze_query, normalize_query
from packages.persistence.db import session_scope
from packages.persistence.models import Entity, IntentCluster, KeywordCandidateRow, SearchObservationRow
from packages.persistence.repositories import audit, get_run, step
from packages.providers.base import ProviderUnavailable
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
            brokers = {e.key: e.name for e in s.scalars(
                select(Entity).where(Entity.project_id == ctx.project.id, Entity.kind == "BROKER", Entity.tracked.is_(True)))}
            languages = [Language(lang) for lang in ctx.settings.get("languages", ["en", "hi", "hi-Latn"])]
            seeds = expand_seeds(brokers, languages)
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
            for provider in trend_providers(ctx):
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
            d.update(seeds_expanded=len(seeds), observations=len(collected), by_language=by_lang, by_source=by_source,
                     provider_failures=failures, data_label="SIMULATED" if ctx.is_simulated else "REAL_PUBLIC")
            audit(s, ctx.project.id, "DISCOVERY_COMPLETED",
                  f"Expanded {len(seeds)} seed queries across {len(languages)} languages; stored {len(collected)} observations",
                  run_id=run.id, payload=d)
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
