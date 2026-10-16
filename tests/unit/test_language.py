import pytest

from packages.contracts.enums import Language, SearchIntent, Theme
from packages.domain.discovery import expand_seeds
from packages.domain.language import analyze_query, detect_language


@pytest.mark.parametrize("query,lang", [
    ("भारत में forex trading legal है क्या", Language.HI),
    ("forex broker se paisa withdraw kaise kare", Language.HINGLISH),
    ("exness login nahi ho raha", Language.HINGLISH),
    ("exness withdrawal time", Language.EN),
    ("is forex trading legal in india", Language.EN),
])
def test_language_detection(query, lang):
    assert detect_language(query) == lang


def test_comparison_intent_is_order_independent():
    assert analyze_query("xm vs exness").intent_key == analyze_query("Exness vs XM which is better").intent_key == "comparison:exness+xm"


def test_years_are_ignored_for_intent_normalisation():
    a, b = analyze_query("is forex trading legal in india 2026"), analyze_query("is forex trading legal in india")
    assert a.normalized == b.normalized and a.intent_key == b.intent_key


def test_cross_language_same_intent():
    keys = {analyze_query(q).intent_key for q in [
        "भारत में forex trading legal है क्या", "is forex trading legal in india", "forex trading legal hai ya nahi"]}
    assert keys == {"regulation:generic"}


@pytest.mark.parametrize("query,theme,intent", [
    ("exness login problem", Theme.LOGIN, SearchIntent.TROUBLESHOOTING),
    ("exness bonus", Theme.BONUS, SearchIntent.TRANSACTIONAL),
    ("octafx alternative india", Theme.ALTERNATIVE, SearchIntent.COMMERCIAL_INVESTIGATION),
    ("फॉरेक्स स्प्रेड क्या है", Theme.FEES, SearchIntent.INFORMATIONAL),
    ("forex leverage kya hai", Theme.LEVERAGE, SearchIntent.INFORMATIONAL),
])
def test_theme_and_intent(query, theme, intent):
    a = analyze_query(query)
    assert a.theme == theme and a.intent == intent


def test_expansion_covers_all_languages_and_modifiers():
    seeds = expand_seeds({"exness": "Exness", "xm": "XM"})
    langs = {s.language for s in seeds}
    mods = {s.modifier for s in seeds}
    assert langs == set(Language)
    assert {"review", "alternative", "vs", "withdrawal", "deposit", "fees", "app", "login", "bonus", "regulation",
            "problems", "support", "spread", "leverage"} <= mods
    assert len({(s.query, s.language) for s in seeds}) == len(seeds)  # no duplicates
