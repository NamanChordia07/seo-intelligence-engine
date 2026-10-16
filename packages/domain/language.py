"""Multilingual (English / Hindi / Hinglish) normalisation, theme + intent classification.

Deterministic and auditable: every classification can be traced to a lexicon hit.
The lexicon maps surface forms in three languages onto shared *concepts*, which is
what lets ATLAS recognise that "exness withdrawal time", "एक्सनेस से पैसे कैसे निकालें"
and "exness se paisa kaise nikale" are the same underlying need.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from packages.contracts.enums import Language, SearchIntent, Theme

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[a-zA-Z]")
YEAR = re.compile(r"\b20[2-3]\d\b")
PUNCT = re.compile(r"[^\w\sऀ-ॿ:+.-]", re.UNICODE)

# ---------------------------------------------------------------------------- entities
BROKERS: dict[str, list[str]] = {
    "exness": ["exness", "एक्सनेस"],
    "xm": ["xm", "xm.com", "xm global", "एक्सएम"],
    "octafx": ["octafx", "octa fx", "octa", "ऑक्टाएफएक्स", "ऑक्टा एफएक्स", "ऑक्टा"],
    "ic-markets": ["ic markets", "icmarkets"],
    "pepperstone": ["pepperstone"],
    "fbs": ["fbs"],
    "olymp-trade": ["olymp trade", "olymptrade"],
    "iq-option": ["iq option", "iqoption"],
}
BROKER_NAMES = {
    "exness": "Exness",
    "xm": "XM",
    "octafx": "OctaFX",
    "ic-markets": "IC Markets",
    "pepperstone": "Pepperstone",
    "fbs": "FBS",
    "olymp-trade": "Olymp Trade",
    "iq-option": "IQ Option",
}

# ---------------------------------------------------------------------------- themes
# Order matters: earlier themes win when several match (most specific first).
THEME_LEXICON: list[tuple[Theme, list[str]]] = [
    (Theme.COMPARISON, [" vs ", " versus ", "बनाम", "compare", "comparison", "तुलना", " ya ", " or "]),
    (Theme.ALTERNATIVE, ["alternative", "alternatives", "विकल्प", "jaisa", "instead of", "similar to", "replacement"]),
    (Theme.NEWS, [" ed ", "raid", "arrest", "attached", "seized", "news", "खबर", "कार्रवाई", "ban news", "probe"]),
    (Theme.BONUS, ["bonus", "बोनस", "promo", "no deposit", "cashback", "offer"]),
    (Theme.WITHDRAWAL, ["withdraw", "withdrawal", "nikal", "निकासी", "निकाल", "विड्रॉल", "विथड्रॉ", "payout"]),
    (Theme.DEPOSIT, ["deposit", "jama", "जमा", "डिपॉजिट", "fund account", "add money", "add fund"]),
    (Theme.LOGIN, ["login", "log in", "sign in", "signin", "लॉगिन", "password", "2fa", "otp"]),
    (Theme.APP, [" app", "apk", "ऐप", "download", "mobile"]),
    (Theme.FEES, ["fee", "fees", "charge", "commission", "spread", "swap", "शुल्क", "फीस", "स्प्रेड", "kharcha", "खर्च", "cost", "लागत"]),
    (Theme.LEVERAGE, ["leverage", "लीवरेज", "margin", "मार्जिन", "1:"]),
    (Theme.REGULATION, ["legal", "illegal", "regulat", "license", "licence", "rbi", "sebi", "fema", "banned", "कानूनी", "लीगल", "वैध", "अवैध", "नियम", "allowed", "permitted"]),
    (Theme.ACCOUNT, ["account", "kyc", "verification", "खाता", "अकाउंट", "suspended", "blocked"]),
    (Theme.TRADING_ISSUES, ["slippage", "requote", "order not", "stop loss", "not executing", "mt5 not", "mt4 not", "chart"]),
    (Theme.SUPPORT, ["customer care", "support", "helpline", "contact", "सपोर्ट", "हेल्पलाइन"]),
    (Theme.REVIEW, ["review", "रिव्यू", "real or fake", "genuine", "scam", "fraud", "safe", "सुरक्षित", "trusted", "reliable"]),
    (Theme.BASICS, ["kya hai", "क्या है", "what is", "how to start", "sikhe", "सीखें", "beginner", "basics", "शुरुआत"]),
]

PROBLEM_MARKERS = [
    "problem", "issue", "not working", "nahi ho", "nahi", "stuck", "failed", "pending", "error", "समस्या",
    "नहीं", "delay", "fix", "thik", "rejected", "kyon", "kyu", "why",
]

HINGLISH_STRONG = {
    "kaise", "kare", "karein", "karna", "hai", "kya", "nahi", "paisa", "paise", "hota", "raha", "rahi", "kyu",
    "kyon", "chahiye", "wala", "wali", "kaun", "sabse", "mein", "hoga", "milega", "hain", "kitna", "kitne",
    "karte", "nikale", "nikalna", "thik", "lagta", "jaata", "bhai", "sahi",
}
HINGLISH_WEAK = {"se", "ka", "ki", "ke", "ya", "me", "ko", "par", "aur"}

# Devanagari / Hinglish surface forms -> canonical token (used for concept tokens / embeddings)
TRANSLIT: dict[str, str] = {
    "फॉरेक्स": "forex", "ट्रेडिंग": "trading", "भारत": "india", "इंडिया": "india", "ब्रोकर": "broker",
    "ऐप": "app", "पैसे": "money", "पैसा": "money", "paisa": "money", "paise": "money", "कैसे": "how",
    "kaise": "how", "क्या": "what", "kya": "what", "लीगल": "legal", "कानूनी": "legal", "वैध": "legal",
    "नियम": "rules", "niyam": "rules", "लागत": "cost", "kharcha": "cost", "खर्च": "cost", "स्प्रेड": "spread",
    "फीस": "fees", "शुल्क": "fees", "लीवरेज": "leverage", "जोखिम": "risk", "jokhim": "risk", "समय": "time",
    "samay": "time", "kitna": "how-much", "कितना": "how-much", "सुरक्षित": "safe", "surakshit": "safe",
    "निकासी": "withdrawal", "निकालें": "withdrawal", "nikale": "withdrawal", "nikalna": "withdrawal",
    "लॉगिन": "login", "विकल्प": "alternative", "बनाम": "vs", "versus": "vs", "time": "time",
    "trading": "trading", "forex": "forex", "withdraw": "withdrawal", "nikal": "withdrawal", "india": "india", "indian": "india", "legal": "legal",
}

STOPWORDS = {
    "the", "a", "an", "in", "of", "to", "for", "is", "are", "and", "on", "with", "from", "how", "what", "my",
    "me", "में", "है", "से", "का", "की", "के", "को", "और", "या", "पर", "hai", "se", "ka", "ki", "ke", "ko",
    "ya", "mein", "kare", "karein", "kaise", "kya", "nahi", "ho", "raha", "hota", "it", "does", "do", "can", "i", "which", "best",
}


@dataclass
class QueryAnalysis:
    normalized: str
    language: Language
    locale: str
    theme: Theme
    intent: SearchIntent
    entity_keys: list[str]
    intent_key: str
    concept_tokens: list[str]
    theme_hits: list[str] = field(default_factory=list)
    has_problem: bool = False


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def normalize_query(query: str, drop_years: bool = True) -> str:
    q = nfc(query).lower().strip()
    q = PUNCT.sub(" ", q)
    if drop_years:
        q = YEAR.sub(" ", q)
    return re.sub(r"\s+", " ", q).strip()


def detect_language(text: str) -> Language:
    deva = len(DEVANAGARI.findall(text))
    latin = len(LATIN.findall(text))
    if deva and deva >= 0.3 * (deva + latin):
        return Language.HI
    tokens = set(re.findall(r"[a-z]+", text.lower()))
    if tokens & HINGLISH_STRONG or len(tokens & HINGLISH_WEAK) >= 2:
        return Language.HINGLISH
    return Language.EN


def locale_for(language: Language) -> str:
    return "hi-IN" if language == Language.HI else "en-IN"


def hreflang_for(language: Language) -> str:
    # Hinglish (hi-Latn) pages are served to the en-IN audience; Google does not treat
    # Latin-script Hindi as a separate hreflang target, so we emit en-IN and record hi-Latn internally.
    return "hi-IN" if language == Language.HI else "en-IN"


def extract_entities(normalized: str) -> list[str]:
    padded = f" {normalized} "
    found: list[str] = []
    for key, aliases in BROKERS.items():
        for alias in aliases:
            if f" {alias} " in padded or (len(alias) > 4 and alias in padded):
                found.append(key)
                break
    # "octa" alias is a substring of "octafx" - collapse
    return sorted(set(found))


def classify_theme(normalized: str, entities: list[str]) -> tuple[Theme, list[str]]:
    padded = f" {normalized} "
    hits: list[tuple[Theme, str]] = []
    for theme, patterns in THEME_LEXICON:
        for p in patterns:
            if p in padded:
                hits.append((theme, p.strip()))
    themes = [t for t, _ in hits]
    # Comparison requires two named entities (or explicit compare wording)
    if Theme.COMPARISON in themes and len(entities) < 2:
        explicit = any(p in ("compare", "comparison", "तुलना") for t, p in hits if t == Theme.COMPARISON)
        if not explicit:
            hits = [(t, p) for t, p in hits if t != Theme.COMPARISON]
            themes = [t for t, _ in hits]
    if not hits:
        return Theme.BASICS, []
    order = [t for t, _ in THEME_LEXICON]
    best = min(themes, key=order.index)
    return best, [p for t, p in hits if t == best]


def classify_intent(theme: Theme, has_problem: bool) -> SearchIntent:
    if theme in (Theme.COMPARISON, Theme.ALTERNATIVE, Theme.REVIEW):
        return SearchIntent.COMMERCIAL_INVESTIGATION
    if theme in (Theme.ACCOUNT, Theme.TRADING_ISSUES, Theme.SUPPORT):
        return SearchIntent.TROUBLESHOOTING
    if theme in (Theme.LOGIN, Theme.APP):
        return SearchIntent.TROUBLESHOOTING if has_problem else SearchIntent.NAVIGATIONAL
    if theme in (Theme.WITHDRAWAL, Theme.DEPOSIT):
        return SearchIntent.TROUBLESHOOTING if has_problem else SearchIntent.INFORMATIONAL
    if theme == Theme.BONUS:
        return SearchIntent.TRANSACTIONAL
    return SearchIntent.INFORMATIONAL


def build_intent_key(theme: Theme, entities: list[str]) -> str:
    """Language-agnostic canonical intent. `xm vs exness` == `exness vs xm`; years ignored."""
    ent = "+".join(sorted(entities)) if entities else "generic"
    return f"{theme.value}:{ent}"


def concept_tokens(normalized: str, theme: Theme, entities: list[str]) -> list[str]:
    tokens: list[str] = [f"C:{theme.value}"] + [f"E:{e}" for e in entities]
    entity_aliases = {a for e in entities for a in BROKERS[e]}
    for raw in normalized.split():
        if raw in entity_aliases or raw in STOPWORDS:
            continue
        tok = TRANSLIT.get(raw, raw)
        if tok in STOPWORDS or len(tok) < 2:
            continue
        tokens.append(tok)
    # de-duplicate, keep order
    seen: set[str] = set()
    return [t for t in tokens if not (t in seen or seen.add(t))]


def analyze_query(query: str) -> QueryAnalysis:
    normalized = normalize_query(query)
    language = detect_language(query)
    entities = extract_entities(normalized)
    theme, hits = classify_theme(normalized, entities)
    padded = f" {normalized} "
    has_problem = any(m in padded for m in PROBLEM_MARKERS)
    intent = classify_intent(theme, has_problem)
    return QueryAnalysis(
        normalized=normalized,
        language=language,
        locale=locale_for(language),
        theme=theme,
        intent=intent,
        entity_keys=entities,
        intent_key=build_intent_key(theme, entities),
        concept_tokens=concept_tokens(normalized, theme, entities),
        theme_hits=hits,
        has_problem=has_problem,
    )
