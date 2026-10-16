"""Deterministic DEMO MODE providers.

Everything returned here is labelled ``source_type=SIMULATED`` (signals/SERPs) or
``retrieval_mode=FIXTURE_SNAPSHOT`` (evidence captured from real public documents).
Nothing simulated is ever presented as a real observation.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from functools import lru_cache

from packages.contracts.enums import (
    Language,
    RetrievalMode,
    SourceClass,
    SourceType,
    VerificationStatus,
)
from packages.contracts.flow import EvidenceClaimItem, EvidenceItem, SearchObservation, SerpResult, SerpSnapshot
from packages.domain.discovery import SeedQuery
from packages.domain.language import analyze_query
from packages.providers.fixtures import day_config, evidence_fixture, serps_fixture

SNAPSHOT_DATE = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


def _obs_time(sim_day: int) -> datetime:
    d = datetime.fromisoformat(day_config(sim_day)["date"]).date()
    return datetime.combine(d, time(6, 0), tzinfo=UTC)


def _to_observation(row: dict, sim_day: int, seed: str | None, source: str, confidence: float) -> SearchObservation:
    a = analyze_query(row["q"])
    return SearchObservation(
        query=row["q"],
        language=a.language,
        locale=a.locale,
        source=source,
        source_type=SourceType.SIMULATED,
        confidence=confidence,
        observed_at=_obs_time(sim_day),
        demand_proxy=float(row["demand"]),
        trend_velocity=float(row["trend"]),
        seed=seed,
        entity_keys=a.entity_keys,
        is_news=bool(row.get("news", False)),
        raw={"fixture_day": sim_day, "via": row.get("via"), "label": "SIMULATED / DEMONSTRATION DATA"},
    )


@lru_cache
def _intent_of(q: str) -> str:
    return analyze_query(q).intent_key


class SimulatedSuggestionProvider:
    """Autocomplete stand-in: returns fixture queries sharing the seed's canonical intent."""

    name = "simulated_autocomplete"

    def suggest(self, seed: SeedQuery, sim_day: int | None) -> list[SearchObservation]:
        if sim_day is None:
            return []
        seed_intent = _intent_of(seed.query)
        rows = [r for r in day_config(sim_day)["observations"] if r.get("via", "suggest") == "suggest"]
        return [
            _to_observation(r, sim_day, seed.query, self.name, 0.6)
            for r in rows
            if _intent_of(r["q"]) == seed_intent
        ]


class SimulatedTrendProvider:
    """Rising-queries + breaking-news stand-in."""

    name = "simulated_trends"

    def rising(self, sim_day: int | None, languages: list[Language]) -> list[SearchObservation]:
        if sim_day is None:
            return []
        out = []
        for r in day_config(sim_day)["observations"]:
            via = r.get("via")
            if via in ("trend", "news"):
                source = "simulated_news" if via == "news" else self.name
                obs = _to_observation(r, sim_day, None, source, 0.7 if via == "news" else 0.55)
                if obs.language in languages:
                    out.append(obs)
        return out


class FixtureSerpProvider:
    name = "simulated_serp"

    def serp(self, query: str, language: Language, intent_key: str) -> SerpSnapshot:
        fx = serps_fixture()
        rows = fx.get(f"{intent_key}|{language.value}") or fx.get(intent_key) or fx["default"]
        results = []
        for i, row in enumerate(rows, start=1):
            ptype, url, title, published, wc, faq, auth, match, heads = row
            results.append(SerpResult(
                position=i, url=url, title=title, domain=url.split("/")[2], page_type=ptype,
                published=published, word_count_estimate=wc, has_faq=bool(faq), authority_proxy=auth,
                intent_match=match, headings=[h.strip() for h in heads.split("|") if h.strip()],
            ))
        return SerpSnapshot(
            query=query, language=language, captured_at=SNAPSHOT_DATE, source=self.name,
            source_type=SourceType.SIMULATED, results=results,
        )


class FixtureEvidenceProvider:
    """Curated snapshots of REAL public documents (verify live before publishing)."""

    name = "evidence_registry"

    def all(self) -> list[EvidenceItem]:
        items = []
        for row in evidence_fixture():
            items.append(EvidenceItem(
                key=row["key"], url=row["url"], title=row["title"], publisher=row["publisher"],
                source_type=SourceType.REAL_PUBLIC, source_class=SourceClass(row["source_class"]),
                retrieval_mode=RetrievalMode.FIXTURE_SNAPSHOT, retrieved_at=SNAPSHOT_DATE,
                published_at=row.get("published_at"), snippet=" ".join(row["snippet"].split()),
                claims=[
                    EvidenceClaimItem(
                        key=c["key"], claim=c["claim"], claim_type=c["type"], confidence=c["confidence"],
                        verification_status=VerificationStatus(c["status"]),
                    )
                    for c in row["claims"]
                ],
                tags=row.get("tags", []),
            ))
        return items

    def by_key(self) -> dict[str, EvidenceItem]:
        return {e.key: e for e in self.all()}

    def find(self, tags: list[str], entity_keys: list[str]) -> list[EvidenceItem]:
        wanted = set(tags) | set(entity_keys)
        scored = []
        for item in self.all():
            overlap = wanted & set(item.tags)
            if overlap:
                scored.append((len(overlap), item))
        scored.sort(key=lambda s: -s[0])
        return [i for _, i in scored]
