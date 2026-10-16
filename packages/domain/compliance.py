"""Deterministic compliance & quality policy engine (authoritative).

LLMs may *add* advisory notes (see workers/compliance), but cannot override a
deterministic outcome: the final status is computed only from the rules below.

Outcome aggregation:  any BLOCK -> BLOCK ; else any REVIEW -> REVIEW ; else PASS.

Publication eligibility is computed separately and also depends on the project's
regulatory authorization status for soliciting Indian residents:
    PROMOTIONAL + authorization UNKNOWN        -> BLOCKED_PENDING_AUTHORIZATION (never auto-approved)
    PROMOTIONAL + authorization NOT_AUTHORIZED -> BLOCKED
    EDUCATIONAL + PASS                         -> ELIGIBLE_EDUCATIONAL
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from packages.contracts.enums import (
    AuthorizationStatus,
    CannibalizationDecision,
    ComplianceStatus,
    ContentClass,
    ContentType,
    Language,
    PublicationEligibility,
    Severity,
    VerificationStatus,
)
from packages.contracts.flow import ComplianceReport, RuleResult
from packages.domain.language import BROKERS

# --------------------------------------------------------------------------- policy text
RISK_WARNINGS: dict[str, str] = {
    "en": (
        "CFDs and leveraged forex products are complex instruments and come with a high risk of losing money "
        "rapidly due to leverage. Only trade with money you can afford to lose. This content is educational "
        "and is not investment advice or an offer to trade."
    ),
    "hi": (
        "CFD और लीवरेज वाले फॉरेक्स उत्पाद जटिल साधन हैं और लीवरेज के कारण तेज़ी से पैसा गंवाने का उच्च जोखिम होता है। "
        "केवल उतना ही पैसा लगाएँ जितना आप खो सकते हैं। यह सामग्री केवल शैक्षिक है, निवेश सलाह या ट्रेड करने का प्रस्ताव नहीं है।"
    ),
    "hi-Latn": (
        "CFD aur leveraged forex products complex instruments hain aur leverage ki wajah se tezi se paisa khone ka "
        "high risk hota hai. Sirf utna hi paisa lagayein jitna aap kho sakte hain. Yeh content sirf educational hai, "
        "investment advice ya trade karne ka offer nahi hai."
    ),
}
RISK_WARNING_MARKERS = {
    "en": "high risk of losing money",
    "hi": "पैसा गंवाने का उच्च जोखिम",
    "hi-Latn": "paisa khone ka high risk",
}

CAUTION_MARKERS = re.compile(
    r"\b(beware|avoid|warn|warning|red flag|no one can|nobody can|cannot guarantee|can't guarantee|can not guarantee|"
    r"never trust|be wary|be suspicious|claims? of|promis\w*|scam|fraud|misleading|do not believe|don't believe|"
    r"no broker|no platform|not possible)\b|सावधान|झांसे|दावा|दावे|वादा|धोखा|bachein|savdhan|jhanse|dhokha|wada|daawa",
    re.IGNORECASE,
)
NEGATION = re.compile(r"\b(not|no|never|neither|nor|isn't|aren't|without being)\b|नहीं|न तो|nahi|nahin", re.IGNORECASE)

PROHIBITED = [
    r"guarantee(?:d|s)?\s+(?:\w+\s+){0,2}(?:profits?|returns?|income|gains?|earnings?)",
    r"risk[\s-]?free", r"\bno risk\b", r"\bzero risk\b", r"\bsure(?:[\s-]shot)?\s+profits?\b", r"assured\s+returns?",
    r"100\s?%\s+(?:safe|profit|returns?|guaranteed)", r"(?:can't|cannot|never)\s+lose", r"double\s+your\s+money",
    r"get\s+rich\s+quick", r"fixed\s+(?:daily|weekly|monthly)\s+(?:profits?|returns?|income)", r"without\s+any\s+risk",
    r"loss[\s-]free",
    r"गारंटी\S*\s+(?:\S+\s+){0,2}(?:मुनाफ|लाभ|रिटर्न|कमाई)", r"बिना\s+(?:किसी\s+)?जोखिम", r"जोखिम[\s-]?मुक्त",
    r"पक्का\s+(?:मुनाफा|प्रॉफिट|लाभ)",
    r"pakka\s+profit", r"guaranteed\s+munafa", r"bina\s+(?:kisi\s+)?risk", r"paisa\s+double", r"fixed\s+munafa",
]
PROHIBITED_RE = re.compile("|".join(PROHIBITED), re.IGNORECASE)

FAKE_REVIEW = re.compile(
    r"\bI\s+(?:made|earned|have been trading|tried|withdrew|deposited|personally|switched)\b|\bmy\s+(?:profits?|earnings?|experience with)\b|"
    r"[★⭐]{3,}|\b\d(?:\.\d)?\s?/\s?5\s+(?:stars?|rating)\b|\bcustomer testimonial\b|\bour users love\b|"
    r"मैंने\s+\S+(?:\s+\S+){0,4}\s+(?:कमाए|कमाया)|maine\s+\S+(?:\s+\S+){0,4}\s+(?:kamaye|kamaya)",
    re.IGNORECASE,
)
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)|<img[^>]*>", re.IGNORECASE)
PROMO_WORDS = re.compile(
    r"\b(?:best|#1|number one|top[\s-]rated|amazing|incredible|unbeatable|exclusive|huge|massive|lowest|fastest|"
    r"instant|limited time|hurry|don't miss|act now|unmatched|superior)\b|सबसे अच्छा|बेहतरीन|zabardast|shandaar",
    re.IGNORECASE,
)
CTA_SOLICIT = re.compile(
    r"\bopen\s+(?:an?\s+|your\s+)?(?:live\s+)?account\b|\bsign\s+up\b|\bregister\s+now\b|\bstart\s+trading\s+(?:now|today)\b|"
    r"\bdeposit\s+now\b|\bclaim\s+(?:your\s+)?bonus\b|\bjoin\s+now\b|\btrade\s+now\b|अकाउंट\s+खोलें|account\s+kholo|abhi\s+join",
    re.IGNORECASE,
)
REGULATOR_TERMS = re.compile(r"\b(?:RBI|SEBI|FEMA|ESMA|FCA|CySEC|Enforcement Directorate)\b|आरबीआई|सेबी|फेमा|प्रवर्तन निदेशालय", re.IGNORECASE)
REG_ENDORSE = re.compile(r"(?:RBI|SEBI|आरबीआई|सेबी)[\s-]*(?:approved|registered|authori[sz]ed|regulated|मान्यता|अधिकृत)|"
                         r"(?:approved|registered|authori[sz]ed|regulated)\s+by\s+(?:the\s+)?(?:RBI|SEBI|Reserve Bank)|"
                         r"\blegal\s+in\s+india\b", re.IGNORECASE)
NUMBER_CLAIM = re.compile(
    r"\d+(?:\.\d+)?\s?%|₹\s?\d|\brs\.?\s?\d|\$\s?\d|€\s?\d|\b\d[\d,.]*\s?(?:crore|lakh|करोड़|लाख|pips?)\b|\b1\s?:\s?\d{2,4}\b",
    re.IGNORECASE,
)
ILLUSTRATIVE = re.compile(r"illustrative|example|for instance|hypothetical|उदाहरण|maan lijiye|maan lo|misaal", re.IGNORECASE)
FOOTNOTE_REF = re.compile(r"\[\^(\d+)\](?!:)")
FOOTNOTE_DEF = re.compile(r"^\[\^(\d+)\]:\s*(.+)$", re.MULTILINE)
URL_RE = re.compile(r"https?://[^\s)>\]]+")
COMPARATIVE = re.compile(
    r"\b(?:better|cheaper|faster|safer|lower|higher|more reliable|more trusted)\s+than\b|\bbeats\b|"
    r"से\s+(?:बेहतर|सस्ता|तेज़)|se\s+(?:behtar|sasta|acha)", re.IGNORECASE,
)
SUPERLATIVE = re.compile(
    r"\b(?:the\s+)?(?:best|safest|cheapest|most trusted|lowest[\s-]spread|fastest)\s+(?:forex\s+|cfd\s+)?(?:broker|platform|app)\b|"
    r"sabse\s+(?:acha|accha|best|sasta)\s+broker|सबसे\s+(?:अच्छा|सस्ता|बेहतर)\s+ब्रोकर|\blowest\s+spreads?\b",
    re.IGNORECASE,
)
AI_CLICHES = re.compile(
    r"in today's fast[\s-]paced|\bdelve\b|navigat\w+ the (?:complex )?(?:world|landscape)|\bunlock the\b|game[\s-]changer|"
    r"it's important to note|a testament to|ever[\s-]evolving|\bseamless(?:ly)?\b|embark on|look no further|elevate your|"
    r"in the realm of|tapestry",
    re.IGNORECASE,
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")

BROKER_ALIASES = sorted({a for aliases in BROKERS.values() for a in aliases if len(a) >= 2}, key=len, reverse=True)
BROKER_RE = re.compile(r"\b(?:" + "|".join(re.escape(a) for a in BROKER_ALIASES if a.isascii()) + r")\b", re.IGNORECASE)


@dataclass
class ComplianceInput:
    markdown: str
    language: Language
    content_class: ContentClass
    content_type: ContentType
    authorization_status: AuthorizationStatus
    evidence_urls: set[str] = field(default_factory=set)
    evidence_status: dict[str, VerificationStatus] = field(default_factory=dict)  # url -> worst claim status
    other_articles: dict[str, str] = field(default_factory=dict)  # label -> markdown
    cannibalization_decision: CannibalizationDecision | None = CannibalizationDecision.NEW_PAGE_OK
    intent_reserved: bool = True
    named_entities: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComplianceRule:
    rule_id: str
    name: str
    category: str
    severity: Severity
    description: str
    check: Callable[[ComplianceInput, Body], tuple[bool, str, list[str], Severity | None]]


# --------------------------------------------------------------------------- text utilities
@dataclass
class Body:
    """Pre-processed article text."""

    full: str
    prose: str  # without frontmatter, risk warning, sources section
    paragraphs: list[str]
    sentences: list[str]
    words: int
    footnote_defs: dict[str, str]


def _strip_sections(md: str) -> str:
    out = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.DOTALL)
    out = re.sub(r"^>\s*\*\*(?:Risk warning|जोखिम चेतावनी|Risk warning \(zaroori\)).*?(?=\n\n|\Z)", "", out, flags=re.MULTILINE | re.DOTALL)
    out = re.sub(r"^##\s+(?:Sources|स्रोत|Sources \(Srot\)).*", "", out, flags=re.MULTILINE | re.DOTALL)
    out = FOOTNOTE_DEF.sub("", out)
    return out


def prepare(md: str) -> Body:
    prose = _strip_sections(md)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", prose) if p.strip()]
    sentences = [s.strip() for s in SENTENCE_SPLIT.split(prose) if len(s.strip()) > 3]
    words = len(re.findall(r"[\wऀ-ॿ]+", prose))
    return Body(full=md, prose=prose, paragraphs=paragraphs, sentences=sentences, words=words,
                footnote_defs=dict(FOOTNOTE_DEF.findall(md)))


def _clip(s: str, n: int = 160) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _shingles(text: str, k: int = 5) -> set[str]:
    toks = re.findall(r"[\wऀ-ॿ]+", text.lower())
    return {" ".join(toks[i : i + k]) for i in range(max(0, len(toks) - k + 1))}


# --------------------------------------------------------------------------- rules
Outcome = tuple[bool, str, list[str], Severity | None]


def r_prohibited(ci: ComplianceInput, b: Body) -> Outcome:
    bad, cautionary = [], 0
    for s in b.sentences:
        if PROHIBITED_RE.search(s):
            if CAUTION_MARKERS.search(s) or NEGATION.search(s):
                cautionary += 1
            else:
                bad.append(_clip(s))
    if bad:
        return False, f"{len(bad)} prohibited performance/safety claim(s) (e.g. guaranteed profit, risk-free)", bad, Severity.BLOCK
    extra = f" ({cautionary} cautionary/negated mention(s) allowed)" if cautionary else ""
    return True, "No prohibited claims" + extra, [], None


def r_risk_warning(ci: ComplianceInput, b: Body) -> Outcome:
    marker = RISK_WARNING_MARKERS[ci.language.value]
    if marker.lower() in b.full.lower():
        return True, f"Required {ci.language.value} risk warning present", [], None
    return False, "Required risk warning missing", [], Severity.BLOCK


def r_citation_integrity(ci: ComplianceInput, b: Body) -> Outcome:
    refs = set(FOOTNOTE_REF.findall(b.full))
    defs = b.footnote_defs
    problems = [f"[^{r}] referenced but not defined" for r in sorted(refs - set(defs))]
    for num, text in defs.items():
        urls = URL_RE.findall(text)
        if not urls:
            problems.append(f"[^{num}] has no URL")
        elif ci.evidence_urls and not any(u.rstrip(".,") in ci.evidence_urls for u in urls):
            problems.append(f"[^{num}] cites a URL not present in the evidence bundle: {urls[0]}")
    if problems:
        return False, "Citation integrity failure (possible fabricated source)", problems, Severity.BLOCK
    return True, f"{len(defs)} citation(s), all traceable to the evidence bundle", [], None


def r_citations_present(ci: ComplianceInput, b: Body) -> Outcome:
    n = len(b.footnote_defs)
    if n == 0:
        return False, "No sources/citations", [], Severity.BLOCK
    if n < 2:
        return False, "Only one source cited - minimum two independent sources", [], Severity.REVIEW
    return True, f"{n} sources cited", [], None


def r_regulatory_claims_cited(ci: ComplianceInput, b: Body) -> Outcome:
    bad = [
        _clip(p) for p in b.paragraphs
        if REGULATOR_TERMS.search(p) and not FOOTNOTE_REF.search(p) and not p.startswith("#") and not p.startswith("|")
        and not p.lstrip().startswith(("- [", "* ["))
        and len(p) > 80
    ]
    if bad:
        return False, f"{len(bad)} paragraph(s) make regulatory statements without a citation", bad[:5], Severity.REVIEW
    return True, "Regulatory statements are cited", [], None


def r_numbers(ci: ComplianceInput, b: Body) -> Outcome:
    bad = []
    for p in b.paragraphs:
        if p.startswith("#"):
            continue
        for s in SENTENCE_SPLIT.split(p):
            if NUMBER_CLAIM.search(s) and not FOOTNOTE_REF.search(s) and not ILLUSTRATIVE.search(p):
                bad.append(_clip(s))
    if bad:
        return False, f"{len(bad)} numeric claim(s) without evidence or 'illustrative example' label", bad[:6], Severity.REVIEW
    return True, "All numeric claims are cited or labelled illustrative", [], None


def r_unverified(ci: ComplianceInput, b: Body) -> Outcome:
    cited_urls = {u.rstrip(".,") for t in b.footnote_defs.values() for u in URL_RE.findall(t)}
    weak = [u for u in cited_urls if ci.evidence_status.get(u) in (VerificationStatus.UNVERIFIED, VerificationStatus.CONFLICTING)]
    labelled = bool(re.search(r"unverified|सत्यापित नहीं|verify nahi", b.prose, re.IGNORECASE))
    if weak:
        msg = "Relies on sources with UNVERIFIED/CONFLICTING claims - human verification required"
        if labelled:
            msg += " (claims are transparently labelled in text)"
        return False, msg, weak, Severity.REVIEW
    return True, "All cited claims are verified (live or snapshot)", [], None


def r_fake_reviews(ci: ComplianceInput, b: Body) -> Outcome:
    hits = [_clip(m.group(0) + " … " + s) for s in b.sentences for m in [FAKE_REVIEW.search(s)] if m]
    if hits:
        return False, "First-person testimonial / rating language detected (fake review risk)", hits[:5], Severity.BLOCK
    return True, "No first-person reviews, ratings or testimonials", [], None


def r_logos(ci: ComplianceInput, b: Body) -> Outcome:
    hits = []
    for m in IMAGE_RE.finditer(b.full):
        blob = m.group(0).lower()
        if "logo" in blob or BROKER_RE.search(blob):
            hits.append(_clip(m.group(0)))
    if hits:
        return False, "Competitor/broker logo or branded image usage", hits, Severity.BLOCK
    return True, "No competitor logos or branded imagery", [], None


def r_promotional(ci: ComplianceInput, b: Body) -> Outcome:
    hits = PROMO_WORDS.findall(b.prose)
    density = 100 * len(hits) / max(b.words, 1)
    if density > 3.0:
        return False, f"Excessive promotional language ({density:.1f} per 100 words)", list(dict.fromkeys(hits))[:10], Severity.BLOCK
    if density > 1.0:
        return False, f"Promotional tone above threshold ({density:.1f} per 100 words)", list(dict.fromkeys(hits))[:10], Severity.REVIEW
    return True, f"Promotional density {density:.2f}/100 words (limit 1.0)", [], None


def r_cta(ci: ComplianceInput, b: Body) -> Outcome:
    hits = [_clip(s) for s in b.sentences if CTA_SOLICIT.search(s) and not NEGATION.search(s) and not CAUTION_MARKERS.search(s)]
    if not hits:
        return True, "No account-opening / deposit solicitation", [], None
    if ci.content_class == ContentClass.EDUCATIONAL:
        return False, "Solicitation CTA inside EDUCATIONAL content (misclassified promotion)", hits, Severity.BLOCK
    if ci.authorization_status == AuthorizationStatus.VERIFIED:
        return True, "Solicitation CTA allowed: authorization VERIFIED", hits, None
    if ci.authorization_status == AuthorizationStatus.NOT_AUTHORIZED:
        return False, "Solicitation of Indian residents while NOT authorized", hits, Severity.BLOCK
    return False, "Solicitation CTA while India authorization is UNKNOWN - legal sign-off required", hits, Severity.REVIEW


def r_misleading_regulatory(ci: ComplianceInput, b: Body) -> Outcome:
    bad = []
    for s in b.sentences:
        if REG_ENDORSE.search(s) and BROKER_RE.search(s) and not NEGATION.search(s) and not re.search(r"\?|\bis\b.*\?|check|verify|whether", s, re.I):
            bad.append(_clip(s))
    if bad:
        return False, "Unsupported claim that a broker is RBI/SEBI approved or legal in India", bad, Severity.BLOCK
    return True, "No misleading regulatory endorsements", [], None


def r_comparisons(ci: ComplianceInput, b: Body) -> Outcome:
    sup = [_clip(s) for s in b.sentences if SUPERLATIVE.search(s) and BROKER_RE.search(s) and not NEGATION.search(s)
           and not CAUTION_MARKERS.search(s)]
    if sup:
        return False, "Superlative claim about a named broker (unverifiable)", sup[:5], Severity.BLOCK
    comp = [_clip(s) for s in b.sentences if COMPARATIVE.search(s) and BROKER_RE.search(s) and not FOOTNOTE_REF.search(s)]
    if comp:
        return False, "Comparative statement about named brokers without evidence", comp[:5], Severity.REVIEW
    return True, "Comparisons are neutral or evidenced", [], None


def r_thin(ci: ComplianceInput, b: Body) -> Outcome:
    h2 = len(re.findall(r"^##\s", b.prose, re.MULTILINE))
    if b.words < 250:
        return False, f"Thin content: {b.words} words", [], Severity.BLOCK
    if b.words < 600 or h2 < 3:
        return False, f"Shallow content: {b.words} words, {h2} sections (min 600 words / 3 sections)", [], Severity.REVIEW
    return True, f"Depth OK: {b.words} words across {h2} sections", [], None


def r_duplicate(ci: ComplianceInput, b: Body) -> Outcome:
    mine = _shingles(b.prose)
    worst, label = 0.0, ""
    for other_label, other_md in ci.other_articles.items():
        theirs = _shingles(_strip_sections(other_md))
        if mine and theirs:
            j = len(mine & theirs) / len(mine | theirs)
            if j > worst:
                worst, label = j, other_label
    if worst > 0.5:
        return False, f"Near-duplicate of '{label}' (5-gram Jaccard {worst:.2f})", [label], Severity.BLOCK
    if worst > 0.25:
        return False, f"High textual overlap with '{label}' ({worst:.2f})", [label], Severity.REVIEW
    return True, f"Unique text (max 5-gram overlap {worst:.2f})", [], None


def r_ai_text(ci: ComplianceInput, b: Body) -> Outcome:
    cliches = AI_CLICHES.findall(b.prose)
    norm = [re.sub(r"\W+", " ", s.lower()).strip() for s in b.sentences if len(s) > 25]
    dup_sent = sum(c - 1 for c in Counter(norm).values() if c > 1)
    toks = re.findall(r"[\wऀ-ॿ]+", b.prose.lower())
    grams = Counter(" ".join(toks[i : i + 4]) for i in range(max(0, len(toks) - 3)))
    top_gram, top_n = (grams.most_common(1)[0] if grams else ("", 0))
    issues = []
    if len(cliches) >= 3:
        issues.append(f"{len(cliches)} AI-cliché phrases: {', '.join(dict.fromkeys(c.lower() for c in cliches))}")
    if norm and dup_sent / len(norm) > 0.05:
        issues.append(f"{dup_sent} repeated sentences")
    if top_n > 6:
        issues.append(f"phrase '{top_gram}' repeated {top_n}x")
    if issues:
        return False, "Suspiciously repetitive / templated AI text", issues, Severity.REVIEW
    return True, "No repetitive or templated-AI patterns", [], None


def r_cannibalization(ci: ComplianceInput, b: Body) -> Outcome:
    if ci.cannibalization_decision not in (None, CannibalizationDecision.NEW_PAGE_OK):
        return False, f"Cannibalization decision {ci.cannibalization_decision.value}", [], Severity.REVIEW
    if not ci.intent_reserved:
        return False, "Intent not reserved - possible duplicate scheduling", [], Severity.BLOCK
    return True, "Unique intent reserved in database", [], None


def r_third_party(ci: ComplianceInput, b: Body) -> Outcome:
    sensitive = ci.content_type in (ContentType.COMPARISON, ContentType.NEWS_ANALYSIS, ContentType.ALTERNATIVES)
    if sensitive and ci.named_entities:
        return False, "Content makes statements about named third parties - editorial/legal review required", ci.named_entities, Severity.REVIEW
    return True, "No named-third-party sensitivity", [], None


def r_promo_authorization(ci: ComplianceInput, b: Body) -> Outcome:
    if ci.content_class != ContentClass.PROMOTIONAL:
        return True, "Educational content - authorization gate not applicable", [], None
    if ci.authorization_status == AuthorizationStatus.VERIFIED:
        return True, "Promotional content: India authorization VERIFIED", [], None
    if ci.authorization_status == AuthorizationStatus.NOT_AUTHORIZED:
        return False, "Promotional content for a platform NOT authorized for Indian residents", [], Severity.BLOCK
    return False, "Promotional content while India authorization is UNKNOWN - publication blocked pending legal verification", [], Severity.REVIEW


RULES: list[ComplianceRule] = [
    ComplianceRule("CMP-001", "Prohibited claims", "misleading", Severity.BLOCK,
                   "Guaranteed profit/returns, risk-free, no risk, sure profit and Hindi/Hinglish equivalents. Cautionary/negated mentions allowed.", r_prohibited),
    ComplianceRule("CMP-002", "Risk warning present", "disclosure", Severity.BLOCK,
                   "Language-appropriate CFD/forex risk warning must be present.", r_risk_warning),
    ComplianceRule("CMP-003", "Citation integrity", "evidence", Severity.BLOCK,
                   "Every footnote is defined and points to a URL in the article's evidence bundle (no fabricated sources).", r_citation_integrity),
    ComplianceRule("CMP-004", "Sources present", "evidence", Severity.REVIEW,
                   "At least two cited sources; zero sources blocks.", r_citations_present),
    ComplianceRule("CMP-005", "Regulatory statements cited", "evidence", Severity.REVIEW,
                   "Paragraphs referencing RBI/SEBI/FEMA/ED/ESMA/FCA/CySEC must carry a citation.", r_regulatory_claims_cited),
    ComplianceRule("CMP-006", "No fabricated numbers", "evidence", Severity.REVIEW,
                   "Percentages, currency amounts, leverage ratios, pips must be cited or labelled illustrative.", r_numbers),
    ComplianceRule("CMP-007", "Unverified claims", "evidence", Severity.REVIEW,
                   "Claims relying on UNVERIFIED or CONFLICTING evidence require human verification.", r_unverified),
    ComplianceRule("CMP-008", "No fake reviews", "integrity", Severity.BLOCK,
                   "No first-person trading testimonials, star ratings or invented user reviews.", r_fake_reviews),
    ComplianceRule("CMP-009", "No competitor logos", "brand", Severity.BLOCK,
                   "No broker logos or branded imagery.", r_logos),
    ComplianceRule("CMP-010", "Promotional tone", "tone", Severity.REVIEW,
                   "Promotional word density <= 1.0 per 100 words (> 3.0 blocks).", r_promotional),
    ComplianceRule("CMP-011", "CTA policy", "solicitation", Severity.BLOCK,
                   "No account-opening/deposit solicitation in educational content; promotional CTAs gated by India authorization.", r_cta),
    ComplianceRule("CMP-012", "Misleading regulatory endorsement", "misleading", Severity.BLOCK,
                   "No unsupported 'RBI/SEBI approved' or 'legal in India' claims about brokers.", r_misleading_regulatory),
    ComplianceRule("CMP-013", "Comparison claims", "misleading", Severity.BLOCK,
                   "Superlatives about named brokers block; uncited comparatives need review.", r_comparisons),
    ComplianceRule("CMP-014", "Content depth", "quality", Severity.REVIEW,
                   ">= 600 words and >= 3 sections (< 250 words blocks).", r_thin),
    ComplianceRule("CMP-015", "Duplicate content", "quality", Severity.BLOCK,
                   "5-gram overlap with other articles: > 0.25 review, > 0.5 block.", r_duplicate),
    ComplianceRule("CMP-016", "Repetitive AI text", "quality", Severity.REVIEW,
                   "AI clichés, repeated sentences, over-repeated phrases.", r_ai_text),
    ComplianceRule("CMP-017", "Cannibalization", "seo", Severity.BLOCK,
                   "Article must hold a unique intent reservation and a NEW_PAGE_OK decision.", r_cannibalization),
    ComplianceRule("CMP-018", "Named third-party review", "legal", Severity.REVIEW,
                   "Comparisons/news/alternatives naming brokers need editorial-legal sign-off.", r_third_party),
    ComplianceRule("CMP-019", "Promotional authorization gate", "solicitation", Severity.BLOCK,
                   "Promotional content requires VERIFIED authorization to solicit Indian residents.", r_promo_authorization),
]


def run_compliance(ci: ComplianceInput) -> ComplianceReport:
    body = prepare(ci.markdown)
    results: list[RuleResult] = []
    for rule in RULES:
        try:
            passed, message, evidence, outcome = rule.check(ci, body)
        except Exception as exc:  # a broken rule must never silently pass
            passed, message, evidence, outcome = False, f"Rule error: {exc}", [], Severity.REVIEW
        results.append(RuleResult(
            rule_id=rule.rule_id, name=rule.name, category=rule.category, severity_on_fail=rule.severity,
            passed=passed, outcome=None if passed else outcome, message=message, evidence=evidence,
        ))

    if any(r.outcome == Severity.BLOCK for r in results):
        status = ComplianceStatus.BLOCK
    elif any(r.outcome == Severity.REVIEW for r in results):
        status = ComplianceStatus.REVIEW
    else:
        status = ComplianceStatus.PASS

    if status == ComplianceStatus.BLOCK:
        elig = PublicationEligibility.BLOCKED
    elif ci.content_class == ContentClass.PROMOTIONAL:
        if ci.authorization_status == AuthorizationStatus.VERIFIED:
            elig = PublicationEligibility.ELIGIBLE_PROMOTIONAL if status == ComplianceStatus.PASS else PublicationEligibility.REQUIRES_HUMAN_REVIEW
        else:
            elig = PublicationEligibility.BLOCKED_PENDING_AUTHORIZATION
    else:
        elig = PublicationEligibility.ELIGIBLE_EDUCATIONAL if status == ComplianceStatus.PASS else PublicationEligibility.REQUIRES_HUMAN_REVIEW

    reasons = [f"{r.rule_id} {r.name}: {r.message}" for r in results if not r.passed]
    if not reasons:
        reasons = ["All deterministic policy rules passed"]
    return ComplianceReport(
        status=status, publication_eligibility=elig, content_class=ci.content_class,
        rule_results=results, reasons=reasons,
    )


def rule_catalog() -> list[dict]:
    return [
        {"rule_id": r.rule_id, "name": r.name, "category": r.category, "severity": r.severity.value, "description": r.description}
        for r in RULES
    ]
