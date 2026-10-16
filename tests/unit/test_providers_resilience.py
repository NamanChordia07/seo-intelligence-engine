"""Failure handling: malformed LLM output, unavailable providers, crawler failures, SSRF guard."""

import httpx
import pytest

from packages.contracts.enums import Language
from packages.domain.briefs import build_brief
from packages.domain.discovery import SeedQuery
from packages.providers.base import GenerationContext, LLMOutputError, ProviderUnavailable
from packages.providers.live import (
    GoogleAutocompleteProvider,
    SafeHttpExtractor,
    SearxngSerpProvider,
    assert_public_url,
)
from packages.providers.llm import OpenAICompatibleLLMProvider, validate_payload
from packages.providers.simulated import FixtureSerpProvider


def brief():
    from packages.contracts.enums import ContentClass, ContentType, SearchIntent, Theme

    return build_brief(keyword="forex spread", secondary=[], language=Language.EN, locale="en-IN", theme=Theme.FEES,
                       intent=SearchIntent.INFORMATIONAL, content_type=ContentType.EXPLAINER,
                       content_class=ContentClass.EDUCATIONAL, intent_key="fees:test", entity_keys=[], library_doc=None,
                       internal_links=[], serp_gaps=[], authorization_status="UNKNOWN", cta_policy="edu")


def test_malformed_llm_output_is_retried_then_rejected(monkeypatch):
    calls = {"n": 0}

    def bad_chat(self, messages):
        calls["n"] += 1
        return "Sure! Here is your article: {not valid json"

    monkeypatch.setattr(OpenAICompatibleLLMProvider, "_chat", bad_chat)
    p = OpenAICompatibleLLMProvider("http://127.0.0.1:9/v1", "m", max_retries=2)
    with pytest.raises(LLMOutputError):
        p.generate_article(brief(), GenerationContext(evidence=[], internal_link_targets=[], plan_date=""))
    assert calls["n"] == 3  # 1 attempt + 2 retries with validation feedback


def test_llm_output_recovers_after_feedback(monkeypatch):
    good = ('{"title":"Forex spreads explained simply","meta_description":"What a forex spread is, how pips work and how to '
            'compare trading costs fairly.","h1":"Forex spreads explained","introduction":"' + "x" * 90 + '",'
            '"sections":[{"heading":"A","body":"' + "b" * 30 + '"},{"heading":"B","body":"' + "b" * 30 + '"},'
            '{"heading":"C","body":"' + "b" * 30 + '"}],"faq":[{"question":"q1","answer":"a"},{"question":"q2","answer":"a"},'
            '{"question":"q3","answer":"a"}]}')
    replies = iter(['{"title": "too short"}', "```json\n" + good + "\n```"])
    monkeypatch.setattr(OpenAICompatibleLLMProvider, "_chat", lambda self, m: next(replies))
    out = OpenAICompatibleLLMProvider("http://x/v1", "m").generate_article(
        brief(), GenerationContext(evidence=[], internal_link_targets=[], plan_date=""))
    assert out.title.startswith("Forex spreads")


def test_validate_payload_rejects_missing_fields():
    with pytest.raises(ValueError):
        validate_payload('{"title": "x"}')


def test_llm_endpoint_down_raises_provider_unavailable():
    p = OpenAICompatibleLLMProvider("http://127.0.0.1:9/v1", "m", timeout=1)
    with pytest.raises(ProviderUnavailable):
        p._chat([{"role": "user", "content": "hi"}])


def test_external_autocomplete_unavailable(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(ProviderUnavailable):
        GoogleAutocompleteProvider().suggest(SeedQuery("exness review", Language.EN, "review", "exness"), None)


def test_searxng_unavailable(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectTimeout("t")))
    with pytest.raises(ProviderUnavailable):
        SearxngSerpProvider("http://searx.invalid").serp("q", Language.EN, "fees:generic")


@pytest.mark.parametrize("url", ["http://localhost/admin", "http://127.0.0.1:5433/", "file:///etc/passwd",
                                 "http://10.0.0.5/", "https://serp.example/x", "ftp://example.com/x"])
def test_ssrf_guard_blocks_internal_urls(url):
    with pytest.raises(ProviderUnavailable):
        assert_public_url(url)


def test_failed_crawler_raises_provider_unavailable():
    with pytest.raises(ProviderUnavailable):
        SafeHttpExtractor().extract("http://this-host-does-not-exist-atlas.invalid/page")


def test_fixture_serp_always_available_and_labelled():
    snap = FixtureSerpProvider().serp("anything", Language.EN, "unknown:intent")
    assert snap.results and snap.source_type.value == "SIMULATED"
    assert all(r.url.split("/")[2].endswith(".example") for r in snap.results)
