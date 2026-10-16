"""Explainable opportunity scoring.

    score = Σ (component_value × weight)      # each component normalised 0-100
            - competition - compliance_risk - overlap

Positive weights sum to 1.0, so a perfect opportunity scores 100. Every component
records its provenance (SIMULATED / PROXY / REAL_PUBLIC) and a human explanation.
This is an ATLAS prioritisation heuristic - not a search-engine metric.
"""

from __future__ import annotations

from packages.contracts.enums import ContentClass, ContentType, SearchIntent, SourceType, Theme
from packages.contracts.flow import KeywordCandidate, ScoreComponent, SerpAnalysis

WEIGHTS: dict[str, float] = {
    "demand": 0.25,
    "trend": 0.15,
    "serp_weakness": 0.20,
    "business_relevance": 0.15,
    "freshness": 0.10,
    "content_gap": 0.15,
    "competition": -0.10,
    "compliance_risk": -0.10,
    "overlap": -0.15,
}

# Editorial relevance of each theme to Indian traders researching platforms (configurable per project)
THEME_RELEVANCE: dict[Theme, float] = {
    Theme.REGULATION: 95, Theme.WITHDRAWAL: 90, Theme.COMPARISON: 85, Theme.ALTERNATIVE: 85, Theme.FEES: 85,
    Theme.DEPOSIT: 80, Theme.LEVERAGE: 80, Theme.LOGIN: 75, Theme.NEWS: 75, Theme.ACCOUNT: 70, Theme.REVIEW: 70,
    Theme.TRADING_ISSUES: 65, Theme.APP: 60, Theme.BASICS: 60, Theme.SUPPORT: 50, Theme.BONUS: 40,
}

COMPLIANCE_RISK: dict[Theme, float] = {Theme.BONUS: 100, Theme.REVIEW: 30, Theme.DEPOSIT: 30, Theme.APP: 20}


def content_type_for(theme: Theme, intent: SearchIntent) -> ContentType:
    if theme == Theme.COMPARISON:
        return ContentType.COMPARISON
    if theme == Theme.ALTERNATIVE:
        return ContentType.ALTERNATIVES
    if theme == Theme.NEWS:
        return ContentType.NEWS_ANALYSIS
    if theme == Theme.BONUS:
        return ContentType.PROMOTIONAL
    if intent == SearchIntent.TROUBLESHOOTING:
        return ContentType.TROUBLESHOOTING
    if theme in (Theme.FEES, Theme.LEVERAGE, Theme.BASICS):
        return ContentType.EXPLAINER
    return ContentType.GUIDE


def content_class_for(content_type: ContentType) -> ContentClass:
    return ContentClass.PROMOTIONAL if content_type == ContentType.PROMOTIONAL else ContentClass.EDUCATIONAL


def _component(key: str, label: str, value: float, source: SourceType, explanation: str) -> ScoreComponent:
    value = max(0.0, min(100.0, value))
    weight = WEIGHTS[key]
    return ScoreComponent(
        key=key, label=label, value=round(value, 1), weight=weight, contribution=round(value * weight, 2),
        source_type=source, explanation=explanation,
    )


def _demand_source(c: KeywordCandidate) -> SourceType:
    if SourceType.SIMULATED in c.source_types:
        return SourceType.SIMULATED
    return SourceType.PROXY


def score_candidate(
    c: KeywordCandidate,
    serp: SerpAnalysis | None,
    max_existing_similarity: float,
    overlap_penalty: float,
) -> tuple[float, list[ScoreComponent], list[str]]:
    comps: list[ScoreComponent] = []
    src = _demand_source(c)

    if c.demand_proxy is not None:
        comps.append(_component("demand", "Demand proxy", c.demand_proxy, src,
                                f"Relative demand index {c.demand_proxy:.0f}/100 ({src.value}). Not an absolute search volume."))
    else:
        comps.append(_component("demand", "Demand proxy", 35, SourceType.PROXY,
                                "No volume data: appearance in public autocomplete used as a weak presence proxy (35/100)."))

    tv = c.trend_velocity or 0.0
    comps.append(_component("trend", "Trend velocity", 50 + tv * 50, src if c.trend_velocity is not None else SourceType.PROXY,
                            f"Change vs previous period: {tv:+.0%} ({src.value})."))

    if serp:
        comps.append(_component("serp_weakness", "SERP weakness", serp.weakness, serp.source_type,
                                "Heuristic from observed results: " + "; ".join(serp.notes[:3])))
    else:
        comps.append(_component("serp_weakness", "SERP weakness", 50, SourceType.PROXY, "No SERP observation; neutral prior."))

    rel = THEME_RELEVANCE.get(c.theme, 50)
    comps.append(_component("business_relevance", "Business relevance", rel, SourceType.PROXY,
                            f"Editorial weight for theme '{c.theme.value}' for Indian trader audience (project config)."))

    if c.is_news and c.is_new_today:
        fresh, why = 100, "Breaking / news-led query first seen today"
    elif c.is_news:
        fresh, why = 80, "News-led query (recent)"
    elif c.is_new_today:
        fresh, why = 85, "Emerging query - first observed today"
    else:
        fresh, why = 40, "Evergreen query (seen on previous days)"
    comps.append(_component("freshness", "Freshness", fresh, src, why))

    gap = 100 * (1 - max_existing_similarity)
    comps.append(_component("content_gap", "Content gap", gap, SourceType.PROXY,
                            f"Max semantic similarity to existing inventory {max_existing_similarity:.2f}."))

    if serp:
        comps.append(_component("competition", "Competition proxy", serp.competition_proxy, serp.source_type,
                                "Average authority proxy of top-5 results (heuristic, not Domain Rating/Authority)."))
    else:
        comps.append(_component("competition", "Competition proxy", 50, SourceType.PROXY, "Unknown; neutral prior."))

    risk = COMPLIANCE_RISK.get(c.theme, 0)
    comps.append(_component("compliance_risk", "Compliance risk", risk, SourceType.PROXY,
                            "Promotional/solicitation-adjacent themes carry publication risk in India." if risk else "Educational theme - low risk."))

    comps.append(_component("overlap", "Cannibalization overlap", overlap_penalty, SourceType.PROXY,
                            "Soft semantic overlap with existing/planned pages." if overlap_penalty else "No meaningful overlap."))

    score = max(0.0, min(100.0, sum(x.contribution for x in comps)))

    why: list[str] = []
    by = {x.key: x for x in comps}
    if by["trend"].value >= 75:
        why.append(f"High trend velocity ({tv:+.0%} vs prior period, {by['trend'].source_type.value})")
    if by["demand"].value >= 65:
        why.append(f"Strong relative demand ({by['demand'].value:.0f}/100, {by['demand'].source_type.value})")
    if serp and serp.weakness >= 45:
        why.append(f"Weak intent match among current results ({serp.avg_intent_match:.0%} avg match, {serp.forum_share:.0%} forum/UGC)")
    if serp and serp.content_gaps:
        why.append("Content gaps in current results: " + ", ".join(serp.content_gaps[:3]))
    if by["content_gap"].value >= 75:
        why.append("No equivalent existing article in inventory")
    if rel >= 80:
        why.append("Strong relevance to target audience")
    if fresh >= 80:
        why.append("Breaking / trending topic - freshness window open" if c.is_news else "Newly emerging query today")
    if risk >= 50:
        why.append("Compliance risk: promotional theme - publication gated by authorization status")
    if overlap_penalty:
        why.append(f"Overlap penalty applied ({overlap_penalty:.0f}/100)")
    return round(score, 1), comps, why

