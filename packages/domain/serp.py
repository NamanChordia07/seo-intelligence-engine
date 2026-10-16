"""SERP / competitor analysis -> explainable weakness + competition proxies.

These are ATLAS heuristics computed from observed result features. They are NOT
Google, Ahrefs or Semrush metrics and are labelled as PROXY / SIMULATED accordingly.
"""

from __future__ import annotations

from datetime import date

from packages.contracts.enums import SourceType, Theme
from packages.contracts.flow import SerpAnalysis, SerpSnapshot
from packages.domain.language import analyze_query

WEAK_PAGE_TYPES = {"forum", "qa", "video", "social", "app_store"}

# Sub-topics a genuinely helpful page for this theme should cover (used for gap detection)
REQUIRED_SUBTOPICS: dict[Theme, list[tuple[str, list[str]]]] = {
    Theme.REGULATION: [
        ("RBI Alert List / authorised ETP check", ["alert list", "etp", "authorised", "authorized"]),
        ("FEMA penalties for residents", ["fema", "penal"]),
        ("Legal routes (exchange-traded currency derivatives)", ["nse", "bse", "exchange", "currency derivative"]),
        ("How to report unauthorised platforms", ["sachet", "report", "complaint"]),
    ],
    Theme.WITHDRAWAL: [
        ("Processing time expectations", ["time", "processing", "how long"]),
        ("KYC / verification causes", ["kyc", "verification", "verify"]),
        ("Payment-method restrictions", ["upi", "bank", "payment method", "card"]),
        ("Escalation & complaint routes", ["complaint", "escalat", "cybercrime", "support"]),
        ("Legal risk for Indian residents", ["fema", "rbi", "legal"]),
    ],
    Theme.COMPARISON: [
        ("Regulatory status verified from registers", ["register", "regulat", "licen"]),
        ("Cost comparison method", ["spread", "commission", "cost"]),
        ("India legality context", ["rbi", "fema", "india"]),
        ("Methodology / how compared", ["method", "how we compare", "criteria"]),
    ],
    Theme.LOGIN: [
        ("Password / 2FA recovery", ["password", "2fa", "otp", "reset"]),
        ("Phishing / fake site warning", ["phishing", "fake", "scam"]),
        ("Account restrictions", ["blocked", "suspended", "restricted"]),
        ("Official support escalation", ["support", "contact"]),
    ],
    Theme.FEES: [
        ("Spread definition & pips", ["spread", "pip"]),
        ("Commission & swap/overnight costs", ["commission", "swap", "overnight", "rollover"]),
        ("Worked cost calculation", ["calculate", "example", "formula"]),
        ("Hidden costs (conversion, inactivity)", ["conversion", "inactivity", "hidden"]),
    ],
    Theme.ALTERNATIVE: [
        ("Why users look for alternatives (news context)", ["ed", "enforcement", "action", "news"]),
        ("Legal alternatives in India", ["sebi", "nse", "bse", "exchange"]),
        ("Verification checklist", ["checklist", "verify", "register"]),
    ],
}
GENERIC_SUBTOPICS = [("Risk disclosure", ["risk"]), ("FAQ", ["faq", "question"])]


def _months_between(published: str | None, ref: date) -> float | None:
    if not published:
        return None
    try:
        y, m = int(published[:4]), int(published[5:7]) if len(published) >= 7 else 1
    except ValueError:
        return None
    return (ref.year - y) * 12 + (ref.month - m)


def _intent_match(result_text: str, candidate_tokens: list[str]) -> float:
    rt = set(analyze_query(result_text).concept_tokens)
    ct = set(candidate_tokens)
    if not ct:
        return 0.0
    return len(rt & ct) / len(ct)


def analyze_serp(snapshot: SerpSnapshot, candidate_tokens: list[str], theme: Theme, plan_date: date) -> SerpAnalysis:
    results = sorted(snapshot.results, key=lambda r: r.position)[:10]
    if not results:
        return SerpAnalysis(
            weakness=50, competition_proxy=50, avg_intent_match=0, forum_share=0, stale_share=0, faq_share=0,
            avg_word_count=None, content_gaps=["No SERP data available - neutral prior used"],
            notes=["SERP unavailable: provider returned no results; neutral 50/50 prior applied"],
            source_type=SourceType.PROXY,
        )
    n = len(results)
    intent_scores = [
        r.intent_match if r.intent_match is not None else _intent_match(f"{r.title} {' '.join(r.headings)}", candidate_tokens)
        for r in results
    ]
    avg_intent = sum(intent_scores) / n
    forum_share = sum(1 for r in results if r.page_type in WEAK_PAGE_TYPES) / n
    ages = [_months_between(r.published, plan_date) for r in results]
    stale_share = sum(1 for a in ages if a is not None and a > 18) / n
    faq_share = sum(1 for r in results if r.has_faq) / n
    wcs = [r.word_count_estimate for r in results if r.word_count_estimate]
    avg_wc = int(sum(wcs) / len(wcs)) if wcs else None
    top5 = results[:5]
    auth = [r.authority_proxy for r in top5 if r.authority_proxy is not None]
    avg_auth = sum(auth) / len(auth) if auth else 0.5

    thin_share = sum(1 for w in wcs if w < 700) / len(wcs) if wcs else 0.0
    weakness = 100 * (
        0.35 * (1 - avg_intent) + 0.25 * forum_share + 0.15 * stale_share + 0.10 * (1 - faq_share) + 0.15 * thin_share
    )
    competition = 100 * avg_auth

    corpus = " ".join(f"{r.title} {r.snippet} {' '.join(r.headings)}".lower() for r in results)
    gaps = [
        label
        for label, needles in REQUIRED_SUBTOPICS.get(theme, []) + GENERIC_SUBTOPICS
        if not any(nd in corpus for nd in needles)
    ]
    notes = [
        f"{forum_share:.0%} of top results are forum/UGC/video pages",
        f"{stale_share:.0%} of results older than 18 months",
        f"Average intent match {avg_intent:.0%} (concept overlap with target query)",
        f"FAQ present on {faq_share:.0%} of results",
    ]
    return SerpAnalysis(
        weakness=round(min(100, weakness), 1),
        competition_proxy=round(competition, 1),
        avg_intent_match=round(avg_intent, 3),
        forum_share=round(forum_share, 3),
        stale_share=round(stale_share, 3),
        faq_share=round(faq_share, 3),
        avg_word_count=avg_wc,
        content_gaps=gaps,
        notes=notes,
        source_type=SourceType.SIMULATED if snapshot.source_type == SourceType.SIMULATED else SourceType.PROXY,
    )
