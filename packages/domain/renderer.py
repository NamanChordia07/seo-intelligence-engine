"""ArticleDraft rendering: payload + evidence + links + policy blocks -> Markdown with frontmatter."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import yaml

from packages.contracts.flow import EvidenceItem, InternalLinkSuggestion, LLMArticlePayload
from packages.domain.compliance import RISK_WARNINGS

CITE_RE = re.compile(r"\[\[E:([a-z0-9\-]+)\]\]")
LINK_RE = re.compile(r"\[\[L:([^|\]]+)\|([^\]]+)\]\]")

LABELS = {
    "en": {"risk": "Risk warning", "faq": "Frequently asked questions", "related": "Related guides", "sources": "Sources",
           "takeaways": "Key takeaways", "table": "Table", "verification": "Verification",
           "cta": "Keep learning: read the related guides above, and always verify a platform's authorisation for Indian residents before moving money.",
           "reviewed": "Evidence reviewed"},
    "hi": {"risk": "जोखिम चेतावनी", "faq": "अक्सर पूछे जाने वाले सवाल", "related": "संबंधित गाइड", "sources": "स्रोत",
           "takeaways": "मुख्य बातें", "table": "तालिका", "verification": "सत्यापन",
           "cta": "और जानने के लिए ऊपर दी गई संबंधित गाइड पढ़ें, और पैसा भेजने से पहले प्लेटफॉर्म की अधिकृत स्थिति ज़रूर जाँचें।",
           "reviewed": "स्रोतों की समीक्षा"},
    "hi-Latn": {"risk": "Risk warning (zaroori)", "faq": "Aksar poochhe jaane wale sawal", "related": "Related guides",
                "sources": "Sources (Srot)", "takeaways": "Main baatein", "table": "Table", "verification": "Verification",
                "cta": "Aur seekhne ke liye upar diye gaye related guides padhein, aur paisa bhejne se pehle platform ki authorisation zaroor check karein.",
                "reviewed": "Evidence reviewed"},
}


@dataclass
class RenderResult:
    markdown: str
    used_evidence_keys: list[str]
    inline_links: list[tuple[str, str, str]]  # (intent_key, slug, anchor)
    dropped_citations: list[str] = field(default_factory=list)
    unresolved_links: list[str] = field(default_factory=list)
    word_count: int = 0


def render_article(
    *, payload: LLMArticlePayload, language: str, frontmatter: dict[str, Any],
    evidence: dict[str, EvidenceItem], resolve_link: Callable[[str], tuple[str, str] | None],
    related: list[InternalLinkSuggestion], related_path: Callable[[InternalLinkSuggestion], str],
    table_after: int | None = None, inject_policy: bool = True, extra_sources: dict[str, dict[str, str]] | None = None,
    retrieved_label: str = "",
) -> RenderResult:
    L = LABELS.get(language, LABELS["en"])
    order: list[str] = []
    dropped: list[str] = []
    inline_links: list[tuple[str, str, str]] = []
    unresolved: list[str] = []
    extra_sources = extra_sources or {}

    def cite(m: re.Match) -> str:
        key = m.group(1)
        if key not in evidence and key not in extra_sources:
            dropped.append(key)
            return ""
        if key not in order:
            order.append(key)
        return f"[^{order.index(key) + 1}]"

    def link(m: re.Match) -> str:
        intent_key, anchor = m.group(1).strip(), m.group(2).strip()
        target = resolve_link(intent_key)
        if target is None:
            unresolved.append(intent_key)
            return anchor
        path, slug = target
        inline_links.append((intent_key, slug, anchor))
        return f"[{anchor}]({path})"

    def tx(text: str) -> str:
        return LINK_RE.sub(link, CITE_RE.sub(cite, text))

    out: list[str] = ["---", yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip(), "---", ""]
    out += [f"# {payload.h1}", ""]
    if inject_policy:
        out += [f"> **{L['risk']}:** {RISK_WARNINGS[language]}", ""]
    out += [tx(payload.introduction), ""]
    if payload.key_takeaways:
        out += [f"**{L['takeaways']}**", ""] + [f"- {tx(k)}" for k in payload.key_takeaways] + [""]

    for i, sec in enumerate(payload.sections):
        out += [f"{'#' * sec.level} {sec.heading}", "", tx(sec.body), ""]
        if payload.table and table_after is not None and i == table_after:
            out += _table(payload, L, tx) + [""]
    if payload.table and (table_after is None or table_after >= len(payload.sections)):
        out += _table(payload, L, tx) + [""]

    out += [f"## {L['faq']}", ""]
    for f in payload.faq:
        out += [f"### {f.question}", "", tx(f.answer), ""]

    if related:
        out += [f"## {L['related']}", ""]
        for r in related:
            out.append(f"- [{r.target_title}]({related_path(r)})")
        out.append("")
    if inject_policy:
        out += [f"> {L['cta']}", ""]

    # Sources must be the final section (compliance strips it when measuring prose).
    out += [f"## {L['sources']}", ""]
    for n, key in enumerate(order, start=1):
        if key in evidence:
            e = evidence[key]
            published = f", published {e.published_at}" if e.published_at else ""
            out.append(
                f"[^{n}]: {e.title} — {e.publisher}{published}. {e.url} "
                f"({e.source_type.value}; {e.retrieval_mode.value}{retrieved_label})"
            )
        else:
            fake = extra_sources[key]
            out.append(f"[^{n}]: {fake.get('title', key)}. {fake['url']}")
    out.append("")
    md = "\n".join(out)
    prose_words = len(re.findall(r"[\wऀ-ॿ]+", md.split("\n---\n", 1)[-1]))
    return RenderResult(markdown=md, used_evidence_keys=[k for k in order if k in evidence], inline_links=inline_links,
                        dropped_citations=dropped, unresolved_links=unresolved, word_count=prose_words)


def _table(payload: LLMArticlePayload, L: dict[str, str], tx: Callable[[str], str]) -> list[str]:
    t = payload.table
    assert t is not None
    n_vals = max(len(r.values) for r in t.rows) if t.rows else 0
    cols = list(t.columns)
    if len(cols) == n_vals + 1:
        cols.append(L["verification"])
    rows = [f"*{L['table']}: {t.caption}*", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in t.rows:
        cells = [r.dimension] + [tx(v) for v in r.values] + [f"`{r.verification}`"]
        rows.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    return rows


def set_frontmatter_value(md: str, key: str, value: str) -> str:
    return re.sub(rf"^{re.escape(key)}: .*$", f"{key}: {value}", md, count=1, flags=re.MULTILINE)
