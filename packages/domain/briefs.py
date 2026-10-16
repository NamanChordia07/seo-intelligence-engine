"""ContentBrief construction (Opportunity -> ContentPlan -> ContentBrief)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from packages.contracts.enums import ContentClass, ContentType, Language, SearchIntent, Theme
from packages.contracts.flow import ContentBrief, InternalLinkSuggestion, OutlineSection
from packages.domain.language import hreflang_for

THEME_OUTLINES: dict[Theme, list[tuple[str, str]]] = {
    Theme.REGULATION: [
        ("Short answer", "Direct answer to the legality question with conditions"),
        ("Permitted instruments and venues", "What the regulator explicitly permits"),
        ("How to verify a platform", "Alert List / authorised list / registration checks"),
        ("Risks of unauthorised platforms", "Legal, recovery and market risk"),
        ("Red flags", "Common fraud patterns"),
        ("Where to complain", "Official reporting channels"),
    ],
    Theme.WITHDRAWAL: [
        ("Check platform authorisation first", "Legal context before troubleshooting"),
        ("Step-by-step process", "Generic withdrawal sequence"),
        ("Common causes of delay", "KYC, payment method, margin, bonus terms"),
        ("If money is stuck", "Escalation and official complaint routes"),
        ("Pre-deposit checklist", "Prevention"),
    ],
    Theme.COMPARISON: [
        ("India legality applies to both", "Authorisation filter first"),
        ("Methodology", "Verification labels and why no winner is declared without data"),
        ("Regulation and licences", "Register-level verification only"),
        ("Trading costs method", "How to compare costs like-for-like"),
        ("Withdrawals", "What could and could not be verified"),
        ("Leverage and risk", "Regulator-sourced risk context"),
    ],
    Theme.LOGIN: [
        ("Rule out an outage", "Platform-side vs user-side"),
        ("Device-side fixes", "Cache, app version, time sync"),
        ("Safe password reset", "Phishing-aware reset flow"),
        ("Lost 2FA", "Recovery via official support"),
        ("Phishing and fake support", "Main risk during outage spikes"),
        ("Account restrictions", "Verification / jurisdiction holds"),
    ],
    Theme.FEES: [
        ("What a spread is", "Definition with source"),
        ("What a pip is", "Unit of measurement"),
        ("Commission and swaps", "Other explicit costs"),
        ("Worked example", "Clearly labelled illustrative calculation"),
        ("Hidden costs", "Conversion, inactivity, slippage"),
        ("How to compare platforms", "Method"),
    ],
    Theme.ALTERNATIVE: [
        ("What has been reported", "Sourced news summary incl. company response"),
        ("Why switching brokers is the wrong question", "Authorisation applies to all"),
        ("Legal alternatives", "Exchange-traded routes"),
        ("Checklist", "Before moving money"),
        ("If funds are on an affected platform", "Recovery-scam warning and official routes"),
    ],
}
DEFAULT_OUTLINE = [
    ("Overview", "Answer the query directly"),
    ("Key considerations", "Facts supported by evidence"),
    ("Risks", "Risk context"),
    ("Next steps", "Safe, educational next steps"),
]
THEME_EVIDENCE_TAGS: dict[Theme, list[str]] = {
    Theme.REGULATION: ["regulation", "india"],
    Theme.WITHDRAWAL: ["withdrawal", "regulation"],
    Theme.COMPARISON: ["comparison", "regulation", "fees"],
    Theme.LOGIN: ["login"],
    Theme.FEES: ["fees"],
    Theme.ALTERNATIVE: ["alternative", "news"],
    Theme.NEWS: ["news", "alternative"],
    Theme.LEVERAGE: ["leverage", "risk"],
    Theme.BONUS: ["regulation"],
}
SOURCES_REQUIRED: dict[Theme, list[str]] = {
    Theme.REGULATION: ["Primary regulator (RBI) on authorised persons/ETPs", "Regulator FAQ on permitted pairs", "Official complaint channel"],
    Theme.WITHDRAWAL: ["Regulator position on unauthorised platforms", "Official fraud-reporting channel"],
    Theme.COMPARISON: ["Regulator registers for each legal entity", "Primary source for any cost/withdrawal figure", "Regulator risk statistics"],
    Theme.LOGIN: ["National cyber-security / fraud-reporting authority"],
    Theme.FEES: ["Definitions of spread, pip, swap from a reference source"],
    Theme.ALTERNATIVE: ["Official enforcement press releases", "Company response", "Regulator position", "Exchange / SEBI registration lists"],
}

LANG_AUDIENCE = {Language.EN: "English", Language.HI: "Hindi (Devanagari)", Language.HINGLISH: "Hinglish (Hindi in Latin script)"}


def ascii_slug(text: str, max_len: int = 70) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t.lower()).strip("-")
    return t[:max_len].rstrip("-") or "article"


def build_brief(
    *, keyword: str, secondary: list[str], language: Language, locale: str, theme: Theme, intent: SearchIntent,
    content_type: ContentType, content_class: ContentClass, intent_key: str, entity_keys: list[str],
    library_doc: dict[str, Any] | None, internal_links: list[InternalLinkSuggestion], serp_gaps: list[str],
    authorization_status: str, cta_policy: str,
) -> ContentBrief:
    outline_src = THEME_OUTLINES.get(theme, DEFAULT_OUTLINE)
    outline = [OutlineSection(heading=h, purpose=p) for h, p in outline_src]
    if library_doc:
        title = library_doc["title"]
        slug = library_doc["slug"]
        angle = " ".join(library_doc.get("angle", "").split())
        audience = library_doc.get("audience", "")
        questions = [f["question"] for f in library_doc.get("faq", [])]
    else:
        title = keyword.strip().capitalize()[:110]
        slug = ascii_slug(f"{theme.value} {' '.join(entity_keys)} {keyword}") or ascii_slug(intent_key)
        angle = "Evidence-first educational answer to the query"
        audience = f"{LANG_AUDIENCE[language]} readers in India"
        questions = [keyword]
    considerations = [
        "Mandatory CFD/forex risk warning in the article language",
        "Every factual/regulatory claim must cite the evidence bundle; omit or label unverified facts",
        "No profit/return promises, no 'risk-free', no first-person reviews or ratings, no broker logos",
        f"Target-platform India authorization: {authorization_status} - "
        + ("educational CTA only" if authorization_status != "VERIFIED" else "promotional CTA permitted after review"),
    ]
    if content_type in (ContentType.COMPARISON, ContentType.ALTERNATIVES, ContentType.NEWS_ANALYSIS):
        considerations.append("Names third parties: neutral wording, include right-of-reply where reported, editorial-legal review")
    if content_class == ContentClass.PROMOTIONAL:
        considerations.append("PROMOTIONAL: publication blocked until authorization to solicit Indian residents is VERIFIED")
    schema = ["Article", "FAQPage", "BreadcrumbList"]
    if content_type == ContentType.NEWS_ANALYSIS or theme == Theme.ALTERNATIVE:
        schema[0] = "NewsArticle (dateline + dateModified on refresh)"
    if content_type == ContentType.TROUBLESHOOTING:
        schema.append("Ordered step list in HTML (HowTo rich results are deprecated by Google; markup optional)")
    return ContentBrief(
        target_keyword=keyword, secondary_keywords=secondary[:8], language=language, locale=locale,
        hreflang=hreflang_for(language), search_intent=intent, content_type=content_type, content_class=content_class,
        recommended_title=title, slug=slug, angle=angle or "Evidence-first educational answer",
        audience=audience or LANG_AUDIENCE[language], outline=outline, questions_to_answer=questions,
        sources_required=SOURCES_REQUIRED.get(theme, ["At least two independent primary/official sources"]),
        internal_links=internal_links,
        compliance_considerations=considerations + ([f"Cover SERP gaps: {', '.join(serp_gaps[:4])}"] if serp_gaps else []),
        cta_policy=cta_policy, schema_recommendations=schema, entity_keys=entity_keys, intent_key=intent_key, theme=theme,
    )
