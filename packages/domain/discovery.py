"""Query expansion: entities x themes x language templates.

Generates the *seed queries* that are sent to suggestion providers. Expansion is
reusable - add a broker or a template and every language picks it up.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts.enums import Language

# {b} = broker display name, {b2} = second broker (comparisons)
TEMPLATES: dict[Language, dict[str, list[str]]] = {
    Language.EN: {
        "review": ["{b} review", "is {b} safe", "{b} real or fake"],
        "alternative": ["{b} alternative", "best alternative to {b} india"],
        "vs": ["{b} vs {b2}"],
        "withdrawal": ["{b} withdrawal time", "{b} withdrawal problem"],
        "deposit": ["{b} deposit upi", "{b} minimum deposit"],
        "fees": ["{b} fees", "{b} charges"],
        "spread": ["{b} spread"],
        "app": ["{b} app", "{b} app not working"],
        "login": ["{b} login problem", "{b} login"],
        "bonus": ["{b} bonus"],
        "regulation": ["is {b} legal in india", "{b} regulation"],
        "problems": ["{b} account problem", "{b} account blocked"],
        "support": ["{b} customer care number"],
        "leverage": ["{b} leverage"],
    },
    Language.HI: {
        "review": ["{b} रिव्यू", "{b} सुरक्षित है या नहीं"],
        "alternative": ["{b} का विकल्प"],
        "vs": ["{b} बनाम {b2}"],
        "withdrawal": ["{b} से पैसे कैसे निकालें"],
        "deposit": ["{b} में पैसे कैसे जमा करें"],
        "fees": ["{b} फीस", "{b} स्प्रेड क्या है"],
        "app": ["{b} ऐप"],
        "login": ["{b} लॉगिन समस्या"],
        "bonus": ["{b} बोनस"],
        "regulation": ["{b} भारत में लीगल है क्या"],
        "problems": ["{b} अकाउंट समस्या"],
        "leverage": ["{b} लीवरेज"],
    },
    Language.HINGLISH: {
        "review": ["{b} safe hai ya nahi", "{b} real hai ya fake"],
        "alternative": ["{b} jaisa dusra broker"],
        "vs": ["{b} ya {b2} kaun sabse acha"],
        "withdrawal": ["{b} se paisa kaise nikale", "{b} withdrawal nahi ho raha"],
        "deposit": ["{b} me paisa kaise jama kare"],
        "fees": ["{b} ka spread kitna hai"],
        "app": ["{b} app kaise download kare"],
        "login": ["{b} login nahi ho raha"],
        "bonus": ["{b} bonus kaise milega"],
        "regulation": ["{b} india me legal hai kya"],
        "problems": ["{b} account block ho gaya"],
        "leverage": ["{b} leverage kitna hai"],
    },
}

TOPIC_SEEDS: dict[Language, list[str]] = {
    Language.EN: [
        "is forex trading legal in india", "forex broker withdrawal problem", "forex spread explained",
        "forex leverage risk", "rbi alert list forex", "forex trading app india",
    ],
    Language.HI: [
        "भारत में forex trading legal है क्या", "फॉरेक्स स्प्रेड क्या है", "फॉरेक्स ट्रेडिंग कैसे सीखें",
        "फॉरेक्स लीवरेज क्या है",
    ],
    Language.HINGLISH: [
        "forex trading legal hai ya nahi", "forex broker se paisa withdraw kaise kare",
        "forex spread kya hota hai", "forex leverage kya hai",
    ],
}


@dataclass(frozen=True)
class SeedQuery:
    query: str
    language: Language
    modifier: str
    entity_key: str | None


def expand_seeds(brokers: dict[str, str], languages: list[Language] | None = None) -> list[SeedQuery]:
    """brokers: key -> display name."""
    langs = languages or list(Language)
    keys = list(brokers)
    seeds: list[SeedQuery] = []
    for lang in langs:
        for modifier, templates in TEMPLATES[lang].items():
            for key in keys:
                for tpl in templates:
                    if "{b2}" in tpl:
                        for other in keys:
                            if other <= key:
                                continue
                            seeds.append(
                                SeedQuery(tpl.format(b=brokers[key], b2=brokers[other]).lower(), lang, modifier, key)
                            )
                    else:
                        seeds.append(SeedQuery(tpl.format(b=brokers[key]).lower(), lang, modifier, key))
        for topic in TOPIC_SEEDS[lang]:
            seeds.append(SeedQuery(topic.lower(), lang, "topic", None))
    # de-duplicate preserving order
    seen: set[tuple[str, str]] = set()
    unique: list[SeedQuery] = []
    for s in seeds:
        k = (s.query, s.language.value)
        if k not in seen:
            seen.add(k)
            unique.append(s)
    return unique


def rotate_seeds(seeds: list[SeedQuery], budget: int, day_ordinal: int) -> list[SeedQuery]:
    """Live runs: a daily request budget can't cover every seed, so rotate a window through the broker seeds
    (different slice each day) while always keeping the broker-agnostic topic seeds."""
    topics = [s for s in seeds if s.entity_key is None]
    brokered = [s for s in seeds if s.entity_key is not None]
    room = max(0, budget - len(topics))
    if not brokered or room == 0:
        return topics[:budget]
    start = (day_ordinal * room) % len(brokered)
    window = (brokered + brokered)[start:start + min(room, len(brokered))]
    return topics + window
