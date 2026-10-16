"""Internal linking engine: relevance-ranked links from new articles to earlier ones.

score = 0.5 * semantic cosine + 0.3 * topical relation + 0.2 * shared entities (+0.05 same language)
Links below the threshold are not forced. Blocked drafts / test fixtures are never link targets.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from packages.contracts.flow import InternalLinkSuggestion
from packages.domain.embedding import cosine

THEME_RELATIONS: dict[str, set[str]] = {
    "regulation": {"withdrawal", "alternative", "comparison", "fees", "login", "leverage", "basics", "news", "review"},
    "withdrawal": {"login", "deposit", "fees", "alternative", "comparison", "regulation", "account"},
    "comparison": {"fees", "regulation", "withdrawal", "review", "alternative", "leverage"},
    "fees": {"comparison", "leverage", "regulation", "withdrawal", "basics"},
    "leverage": {"fees", "regulation", "basics", "comparison"},
    "alternative": {"regulation", "comparison", "news", "withdrawal"},
    "login": {"withdrawal", "account", "regulation", "app"},
    "basics": {"leverage", "fees", "regulation"},
    "news": {"alternative", "regulation"},
}
LINK_THRESHOLD = 0.40
REVERSE_THRESHOLD = 0.55
MAX_LINKS = 4


@dataclass
class LinkTarget:
    id: UUID
    slug: str
    title: str
    path: str
    theme: str
    intent_key: str
    entity_keys: list[str]
    language: str
    embedding: list[float] | None
    origin: str


def related(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return 1.0 if b in THEME_RELATIONS.get(a, set()) or a in THEME_RELATIONS.get(b, set()) else 0.0


def suggest_links(
    theme: str, entity_keys: list[str], language: str, embedding: list[float] | None,
    targets: list[LinkTarget], exclude_ids: set[UUID] | None = None,
) -> list[InternalLinkSuggestion]:
    exclude_ids = exclude_ids or set()
    scored: list[tuple[float, LinkTarget, str]] = []
    for t in targets:
        if t.id in exclude_ids:
            continue
        sem = max(0.0, cosine(embedding, t.embedding))
        rel = related(theme, t.theme)
        ents = set(entity_keys) & set(t.entity_keys)
        ent = 1.0 if ents else 0.0
        score = 0.5 * sem + 0.3 * rel + 0.2 * ent + (0.05 if t.language == language else 0.0)
        if score < LINK_THRESHOLD:
            continue
        reasons = []
        if rel:
            reasons.append(f"topical relation {theme}→{t.theme}")
        if ents:
            reasons.append("shared entities: " + ", ".join(sorted(ents)))
        if sem >= 0.2:
            reasons.append(f"semantic {sem:.2f}")
        if t.language != language:
            reasons.append(f"cross-language ({t.language})")
        scored.append((score, t, "; ".join(reasons) or "related"))
    scored.sort(key=lambda s: -s[0])
    return [
        InternalLinkSuggestion(target_article_id=t.id, target_slug=t.slug, target_title=t.title, anchor_text=t.title,
                               score=round(s, 3), reason=r)
        for s, t, r in scored[:MAX_LINKS]
    ]
