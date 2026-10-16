"""Cannibalization engine - multiple independent safeguards, deterministic decision.

Checks (each recorded with score / threshold / triggered):
  1. intent_key        - normalised canonical intent (theme + sorted entities, language-agnostic)
  2. keyword_overlap   - Jaccard over concept tokens
  3. semantic          - cosine similarity of concept-hash embeddings (pgvector)
  4. entity_subsumption- same theme, one side generic / entity subset + semantic support
  5. serp_overlap      - Jaccard of ranking URLs between the two SERPs
  6. slug              - proposed slug already exists

The database then enforces the final guarantee with a UNIQUE(project_id, intent_key)
reservation, so even concurrent runs cannot schedule the same intent twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from packages.contracts.enums import CannibalizationDecision
from packages.contracts.flow import CannibalizationCheck, CannibalizationResult
from packages.domain.embedding import cosine

KEYWORD_OVERLAP_THRESHOLD = 0.6
SEMANTIC_HARD_THRESHOLD = 0.82
SEMANTIC_SOFT_THRESHOLD = 0.45
SERP_OVERLAP_THRESHOLD = 0.4


@dataclass
class InventoryItem:
    kind: str  # "article" | "opportunity"
    id: UUID
    label: str
    intent_key: str
    theme: str
    language: str
    entity_keys: list[str]
    concept_tokens: list[str]
    embedding: list[float] | None
    slug: str | None = None
    serp_urls: set[str] = field(default_factory=set)
    blocked: bool = False


@dataclass
class CandidateView:
    intent_key: str
    theme: str
    language: str
    entity_keys: list[str]
    concept_tokens: list[str]
    embedding: list[float] | None
    slug: str | None
    serp_urls: set[str]


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _strip(tokens: list[str]) -> set[str]:
    return {t for t in tokens if not t.startswith("C:")}


def evaluate(candidate: CandidateView, inventory: list[InventoryItem]) -> tuple[CannibalizationResult, float, float]:
    """Return (result, max_similarity_to_articles, soft_overlap_penalty_0_100)."""
    checks: list[CannibalizationCheck] = []
    hard: list[tuple[str, InventoryItem, float]] = []
    soft: list[tuple[InventoryItem, float]] = []
    max_article_sim = 0.0

    for item in inventory:
        sem = cosine(candidate.embedding, item.embedding)
        if item.kind == "article":
            max_article_sim = max(max_article_sim, sem)
        kw = jaccard(_strip(candidate.concept_tokens), _strip(item.concept_tokens))
        serp = jaccard(candidate.serp_urls, item.serp_urls)
        same_theme = candidate.theme == item.theme
        ent_c, ent_i = set(candidate.entity_keys), set(item.entity_keys)
        subsumed = same_theme and (not ent_c or not ent_i or ent_c <= ent_i or ent_i <= ent_c)

        def add(check: str, score: float, threshold: float, triggered: bool, detail: str,
                _item: InventoryItem = item) -> None:
            checks.append(CannibalizationCheck(
                check=check, score=round(score, 3), threshold=threshold, triggered=triggered,
                against_article_id=_item.id if _item.kind == "article" else None,
                against_opportunity_id=_item.id if _item.kind == "opportunity" else None,
                against_label=_item.label, detail=detail,
            ))

        if candidate.slug and item.slug and candidate.slug == item.slug:  # always checked, any topic
            add("slug", 1.0, 1.0, True, f"slug '{candidate.slug}' already used")
            hard.append(("slug", item, 1.0))

        relevant = same_theme or sem >= SEMANTIC_SOFT_THRESHOLD or candidate.intent_key == item.intent_key
        if not relevant:
            continue

        exact = candidate.intent_key == item.intent_key
        add("intent_key", 1.0 if exact else 0.0, 1.0, exact,
            f"canonical intent '{candidate.intent_key}' vs '{item.intent_key}'")
        if exact:
            hard.append(("intent_key", item, 1.0))

        kw_hit = kw >= KEYWORD_OVERLAP_THRESHOLD
        add("keyword_overlap", kw, KEYWORD_OVERLAP_THRESHOLD, kw_hit, "Jaccard over concept tokens")
        if kw_hit and same_theme:
            hard.append(("keyword_overlap", item, kw))

        sem_hit = sem >= SEMANTIC_HARD_THRESHOLD
        add("semantic", sem, SEMANTIC_HARD_THRESHOLD, sem_hit, "cosine similarity (concept-hash embedding)")
        if sem_hit:
            hard.append(("semantic", item, sem))

        sub_hit = subsumed and sem >= SEMANTIC_SOFT_THRESHOLD and not exact
        add("entity_subsumption", sem if subsumed else 0.0, SEMANTIC_SOFT_THRESHOLD, sub_hit,
            "same theme; broker-specific vs generic page (or entity subset)")
        if sub_hit:
            soft.append((item, sem))

        if candidate.serp_urls and item.serp_urls:
            serp_hit = serp >= SERP_OVERLAP_THRESHOLD
            add("serp_overlap", serp, SERP_OVERLAP_THRESHOLD, serp_hit, "shared ranking URLs between SERPs")
            if serp_hit:
                hard.append(("serp_overlap", item, serp))

    penalty = 0.0
    if hard:
        check, item, score = max(hard, key=lambda h: (h[0] == "intent_key", h[2]))
        same_lang = item.language == candidate.language
        if item.kind == "opportunity":
            decision = CannibalizationDecision.REJECT_NEW_PAGE if same_lang or check != "intent_key" else CannibalizationDecision.LOCALE_VARIANT
            reason = (
                f"Duplicate of opportunity already selected/planned: '{item.label}' ({check}={score:.2f})"
                if decision == CannibalizationDecision.REJECT_NEW_PAGE
                else f"Same intent as planned '{item.label}' in another language - schedule later as hreflang alternate"
            )
        else:
            if check == "intent_key" and not same_lang:
                decision = CannibalizationDecision.LOCALE_VARIANT
                reason = f"Intent already covered by '{item.label}' ({item.language}); create only as a localized hreflang alternate"
            elif item.blocked:
                decision = CannibalizationDecision.REJECT_NEW_PAGE
                reason = f"Intent previously attempted by blocked draft '{item.label}' - requires human decision"
            else:
                decision = CannibalizationDecision.UPDATE_EXISTING_PAGE
                reason = f"Existing article '{item.label}' already targets this intent ({check}={score:.2f}) - refresh it instead"
        return CannibalizationResult(
            decision=decision, reason=reason,
            conflicting_article_id=item.id if item.kind == "article" else None,
            conflicting_opportunity_id=item.id if item.kind == "opportunity" else None,
            checks=checks,
        ), max_article_sim, 100.0

    if soft:
        item, score = max(soft, key=lambda s: s[1])
        if item.kind == "article" and not item.blocked:
            return CannibalizationResult(
                decision=CannibalizationDecision.UPDATE_EXISTING_PAGE,
                reason=f"Broker-specific/generic variant of existing '{item.label}' (semantic {score:.2f}) - add a section to that page instead of a competing URL",
                conflicting_article_id=item.id, checks=checks,
            ), max_article_sim, 80.0
        if item.kind == "opportunity":
            return CannibalizationResult(
                decision=CannibalizationDecision.REJECT_NEW_PAGE,
                reason=f"Overlaps with today's selected '{item.label}' (semantic {score:.2f})",
                conflicting_opportunity_id=item.id, checks=checks,
            ), max_article_sim, 80.0

    top_sem = max((c.score for c in checks if c.check == "semantic"), default=0.0)
    if top_sem >= 0.3:
        penalty = round((top_sem - 0.3) / (SEMANTIC_HARD_THRESHOLD - 0.3) * 60, 1)
    return CannibalizationResult(
        decision=CannibalizationDecision.NEW_PAGE_OK,
        reason="No conflicting intent, keyword, semantic, SERP or slug overlap detected",
        checks=checks,
    ), max_article_sim, penalty
