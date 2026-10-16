"""Contract tests: fixtures and models conform to the flow contract."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from packages.contracts.enums import Language, RetrievalMode, SourceType
from packages.contracts.flow import ContentBrief, LLMArticlePayload, SearchObservation
from packages.domain.compliance import RISK_WARNINGS, rule_catalog
from packages.domain.language import analyze_query
from packages.providers.fixtures import content_library, days_fixture, inventory_fixture, serps_fixture
from packages.providers.llm import DemoLLMProvider
from packages.providers.simulated import FixtureEvidenceProvider


@pytest.mark.parametrize("intent_key", sorted(content_library()))
def test_every_library_draft_is_a_valid_payload(intent_key):
    payload = DemoLLMProvider().generate_article(SimpleNamespace(intent_key=intent_key), None)
    assert isinstance(payload, LLMArticlePayload)
    assert analyze_query(content_library()[intent_key]["title"]) is not None


def test_library_citations_reference_registry_keys():
    import re

    keys = set(FixtureEvidenceProvider().by_key())
    for ik, doc in content_library().items():
        fake = {f["key"] for f in doc.get("fake_sources", [])}
        cited = set(re.findall(r"\[\[E:([a-z0-9\-]+)\]\]", str(doc)))
        assert cited - keys <= fake, f"{ik} cites unknown evidence {cited - keys - fake}"


def test_evidence_registry_is_real_public_snapshots():
    items = FixtureEvidenceProvider().all()
    assert len(items) >= 10
    for e in items:
        assert e.source_type == SourceType.REAL_PUBLIC and e.retrieval_mode == RetrievalMode.FIXTURE_SNAPSHOT
        assert e.url.startswith("https://") and e.claims


def test_day_fixtures_cover_three_days_and_languages():
    days = days_fixture()
    assert {"day1", "day2", "day3"} <= set(days)
    langs = {analyze_query(o["q"]).language for d in days.values() for o in d["observations"]}
    assert langs == set(Language)


def test_simulated_serps_use_reserved_domains():
    for key, rows in serps_fixture().items():
        for row in rows:
            assert row[1].split("/")[2].endswith(".example"), key


def test_inventory_and_policy_text_present():
    assert len(inventory_fixture()) >= 3
    assert set(RISK_WARNINGS) == {"en", "hi", "hi-Latn"}
    assert len(rule_catalog()) >= 15


def test_brief_slug_validation():
    with pytest.raises(ValidationError):
        ContentBrief.model_validate({"slug": "Bad Slug!"} | {k: None for k in ContentBrief.model_fields if k != "slug"})


def test_observation_rejects_out_of_range_signals():
    from datetime import UTC, datetime

    with pytest.raises(ValidationError):
        SearchObservation(query="exness", language=Language.EN, locale="en-IN", source="x", source_type=SourceType.SIMULATED,
                          confidence=1.5, observed_at=datetime.now(UTC))
