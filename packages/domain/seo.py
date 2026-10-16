"""SEO packaging: metadata checks, canonical/hreflang, JSON-LD and technical recommendations.

Ranking is an optimisation objective, never a promise: nothing here claims a position.
"""

from __future__ import annotations

from typing import Any

from packages.contracts.enums import Language

SITE_SECTIONS = {"en": "en-in", "hi": "hi-in", "hi-Latn": "en-in"}


def article_path(language: str, slug: str) -> str:
    return f"/{SITE_SECTIONS.get(language, 'en-in')}/guides/{slug}"


def canonical_url(domain: str, language: str, slug: str) -> str:
    return f"https://{domain}{article_path(language, slug)}"


TECHNICAL_RECOMMENDATIONS = [
    {"area": "Rendering", "item": "Server-render (SSR/SSG) article HTML so content and JSON-LD are in the initial response."},
    {"area": "Mobile-first", "item": "Single-column layout <= 70ch line length, 16px+ base font, tap targets >= 48px; Hindi uses a Devanagari-capable font stack (e.g. Noto Sans Devanagari) with font-display: swap."},
    {"area": "Core Web Vitals", "item": "Targets: LCP < 2.5s, INP < 200ms, CLS < 0.1 on a mid-range Android over 4G; avoid client-only rendering of article body."},
    {"area": "Images", "item": "AVIF/WebP, explicit width/height to prevent CLS, lazy-load below the fold, no broker logos (compliance)."},
    {"area": "Tables", "item": "Wrap comparison tables in a horizontally scrollable container on mobile; keep the first column sticky."},
    {"area": "Canonical", "item": "Self-referencing canonical on every article; refreshed pages keep their URL (update dateModified)."},
    {"area": "hreflang", "item": "Reciprocal hreflang between en-IN and hi-IN alternates of the same intent, plus x-default."},
    {"area": "Sitemap", "item": "XML sitemap with <lastmod> per article and per-locale sitemap files; submit in Search Console."},
    {"area": "Robots", "item": "Index educational pages; noindex blocked/review drafts and internal search; never cloak content for bots."},
    {"area": "Internal links", "item": "Contextual in-body links + related-guide module; avoid orphan pages; descriptive anchors in the page language."},
    {"area": "Freshness", "item": "Re-verify regulatory snapshots on a schedule; show 'last reviewed' date; refresh rather than duplicate."},
]


def build_seo(
    *, title: str, meta_description: str, h1: str, slug: str, language: str, locale: str, hreflang: str,
    domain: str, faq: list[dict[str, str]], generated_at: str, intent_key: str,
    locale_alternates: list[dict[str, str]] | None = None, schema_types: list[str] | None = None,
    breadcrumb_section: str = "Guides",
) -> dict[str, Any]:
    canonical = canonical_url(domain, language, slug)
    checks = []
    tl, ml = len(title), len(meta_description)
    checks.append({"check": "title_length", "value": tl, "ok": tl <= 65,
                   "note": "<= 60-65 chars recommended to limit truncation" if tl > 65 else "ok"})
    checks.append({"check": "meta_description_length", "value": ml, "ok": 70 <= ml <= 165,
                   "note": "70-160 chars recommended"})
    checks.append({"check": "h1_differs_from_title", "value": h1 != title, "ok": True,
                   "note": "H1 may differ from <title> to cover a variant phrasing"})
    hreflangs = [{"hreflang": hreflang, "href": canonical}]
    for alt in locale_alternates or []:
        hreflangs.append(alt)
    hreflangs.append({"hreflang": "x-default", "href": canonical})
    article_type = "NewsArticle" if schema_types and schema_types[0].startswith("NewsArticle") else "Article"
    jsonld_article = {
        "@context": "https://schema.org", "@type": article_type, "headline": h1[:110], "description": meta_description,
        "inLanguage": "hi-Latn" if language == Language.HINGLISH.value else locale,
        "mainEntityOfPage": canonical, "datePublished": generated_at, "dateModified": generated_at,
        "author": {"@type": "Organization", "name": "Editorial team (to be named before publication)"},
        "publisher": {"@type": "Organization", "name": domain},
    }
    jsonld_faq = {
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": f["question"], "acceptedAnswer": {"@type": "Answer", "text": f["answer"]}}
            for f in faq
        ],
    }
    jsonld_breadcrumb = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"https://{domain}/"},
            {"@type": "ListItem", "position": 2, "name": breadcrumb_section, "item": f"https://{domain}/{SITE_SECTIONS.get(language, 'en-in')}/guides"},
            {"@type": "ListItem", "position": 3, "name": h1[:80], "item": canonical},
        ],
    }
    return {
        "title": title, "meta_description": meta_description, "h1": h1, "slug": slug, "canonical": canonical,
        "path": article_path(language, slug), "language": language, "locale": locale, "hreflang": hreflangs,
        "hreflang_note": ("Hinglish content is tagged hi-Latn internally and served to the en-IN audience; "
                          "Google does not treat Latin-script Hindi as a separate hreflang target.")
        if language == Language.HINGLISH.value else None,
        "schema_recommendations": schema_types or ["Article", "FAQPage", "BreadcrumbList"],
        "json_ld": {"article": jsonld_article, "faq": jsonld_faq, "breadcrumb": jsonld_breadcrumb},
        "checks": checks, "technical": TECHNICAL_RECOMMENDATIONS, "intent_key": intent_key,
        "ranking_note": "Ranking is an optimisation objective (intent match, evidence, internal links, UX), not a guarantee.",
    }
