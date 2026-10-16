import uuid

from packages.contracts.enums import CannibalizationDecision, Language, SearchIntent, SourceType, Theme
from packages.contracts.flow import KeywordCandidate
from packages.domain.cannibalization import CandidateView, InventoryItem, evaluate
from packages.domain.embedding import cosine, get_embedder
from packages.domain.language import analyze_query
from packages.domain.scoring import WEIGHTS, score_candidate

E = get_embedder()


def view(q: str, slug: str | None = None, urls: set[str] | None = None) -> CandidateView:
    a = analyze_query(q)
    return CandidateView(intent_key=a.intent_key, theme=a.theme.value, language=a.language.value, entity_keys=a.entity_keys,
                         concept_tokens=a.concept_tokens, embedding=E.embed(a.concept_tokens), slug=slug, serp_urls=urls or set())


def item(q: str, kind: str = "article", slug: str | None = None, urls: set[str] | None = None) -> InventoryItem:
    a = analyze_query(q)
    return InventoryItem(kind=kind, id=uuid.uuid4(), label=q, intent_key=a.intent_key, theme=a.theme.value,
                         language=a.language.value, entity_keys=a.entity_keys, concept_tokens=a.concept_tokens,
                         embedding=E.embed(a.concept_tokens), slug=slug, serp_urls=urls or set())


def test_duplicate_keyword_same_language_updates_existing():
    res, _, _ = evaluate(view("exness vs xm which is better"), [item("xm vs exness")])
    assert res.decision == CannibalizationDecision.UPDATE_EXISTING_PAGE
    assert any(c.check == "intent_key" and c.triggered for c in res.checks)


def test_duplicate_within_todays_plan_is_rejected():
    res, _, _ = evaluate(view("exness vs xm"), [item("xm vs exness", kind="opportunity")])
    assert res.decision == CannibalizationDecision.REJECT_NEW_PAGE


def test_same_intent_other_language_is_locale_variant():
    res, _, _ = evaluate(view("is forex trading legal in india"), [item("भारत में forex trading legal है क्या")])
    assert res.decision == CannibalizationDecision.LOCALE_VARIANT


def test_semantic_broker_variant_of_generic_page():
    res, _, _ = evaluate(view("is exness legal in india"), [item("is forex trading legal in india")])
    assert res.decision == CannibalizationDecision.UPDATE_EXISTING_PAGE
    assert any(c.check == "entity_subsumption" and c.triggered for c in res.checks)


def test_duplicate_slug_detected():
    res, _, _ = evaluate(view("forex broker withdrawal problem", slug="my-slug"),
                         [item("exness login problem", slug="my-slug")])
    assert any(c.check == "slug" and c.triggered for c in res.checks)


def test_serp_overlap_detected():
    urls = {f"https://x.example/{i}" for i in range(5)}
    res, _, _ = evaluate(view("exness app", urls=urls), [item("exness app download", urls=urls)])
    assert any(c.check == "serp_overlap" and c.triggered for c in res.checks)


def test_unrelated_topics_are_fine():
    res, _, _ = evaluate(view("फॉरेक्स स्प्रेड क्या है"), [item("exness login problem")])
    assert res.decision == CannibalizationDecision.NEW_PAGE_OK


def test_cross_language_paraphrases_are_close():
    a = analyze_query("forex spread kya hota hai")
    b = analyze_query("फॉरेक्स स्प्रेड क्या है")
    assert cosine(E.embed(a.concept_tokens), E.embed(b.concept_tokens)) > 0.8


def test_scoring_is_explainable_and_labelled():
    c = KeywordCandidate(normalized_query="q", display_query="q", language=Language.EN, locale="en-IN", theme=Theme.REGULATION,
                         intent=SearchIntent.INFORMATIONAL, entity_keys=[], intent_key="regulation:generic", concept_tokens=[],
                         demand_proxy=80, trend_velocity=0.5, source_types=[SourceType.SIMULATED], is_new_today=True)
    score, comps, why = score_candidate(c, None, 0.1, 0.0)
    assert 0 <= score <= 100
    assert abs(score - sum(x.contribution for x in comps)) < 0.5
    assert {x.key for x in comps} == set(WEIGHTS)
    assert next(x for x in comps if x.key == "demand").source_type == SourceType.SIMULATED
    assert all(x.explanation for x in comps) and why
    assert abs(sum(w for w in WEIGHTS.values() if w > 0) - 1.0) < 1e-9
