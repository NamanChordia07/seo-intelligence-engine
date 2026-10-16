"""Deterministic compliance engine - including intentional failure cases."""

import re
from types import SimpleNamespace

import pytest

from packages.contracts.enums import (
    AuthorizationStatus,
    ComplianceStatus,
    ContentClass,
    ContentType,
    Language,
    PublicationEligibility,
)
from packages.domain.compliance import RISK_WARNINGS, ComplianceInput, run_compliance
from packages.domain.renderer import render_article
from packages.providers.fixtures import content_library
from packages.providers.llm import DemoLLMProvider
from packages.providers.simulated import FixtureEvidenceProvider

EVIDENCE = FixtureEvidenceProvider().by_key()
URLS = {e.url for e in EVIDENCE.values()}


def _render(intent_key):
    doc = content_library()[intent_key]
    payload = DemoLLMProvider().generate_article(SimpleNamespace(intent_key=intent_key), None)
    return render_article(
        payload=payload, language=doc["language"], frontmatter={"compliance_status": "PENDING"}, evidence=EVIDENCE,
        resolve_link=lambda k: None, related=[], related_path=lambda r: "#",
        table_after=(doc.get("table") or {}).get("after_section"), inject_policy=not doc.get("skip_policy_injection"),
        extra_sources={f["key"]: f for f in doc.get("fake_sources", [])},
    ).markdown, doc


# A real, compliant rendered article used as the baseline that each test mutates.
GOOD = _render("login:exness")[0]
ANCHOR = "It is independent and not affiliated"
assert ANCHOR in GOOD


def inject(text: str) -> str:
    return GOOD.replace(ANCHOR, f"{text} {ANCHOR}")


def ci(md: str, **kw) -> ComplianceInput:
    base = dict(markdown=md, language=Language.EN, content_class=ContentClass.EDUCATIONAL,
                content_type=ContentType.TROUBLESHOOTING, authorization_status=AuthorizationStatus.UNKNOWN,
                evidence_urls=URLS)
    base.update(kw)
    return ComplianceInput(**base)


def failed(report) -> dict[str, str]:
    return {r.rule_id: r.outcome.value for r in report.rule_results if not r.passed}


def test_clean_educational_content_passes():
    r = run_compliance(ci(GOOD))
    assert r.status == ComplianceStatus.PASS, failed(r)
    assert r.publication_eligibility == PublicationEligibility.ELIGIBLE_EDUCATIONAL


def test_guaranteed_profit_claim_is_blocked():
    r = run_compliance(ci(inject("Earn guaranteed profits with zero risk.")))
    assert r.status == ComplianceStatus.BLOCK
    assert failed(r)["CMP-001"] == "BLOCK"


@pytest.mark.parametrize("phrase", ["यह गारंटीड मुनाफा देता है।", "Isme pakka profit hai.", "This strategy is risk-free."])
def test_multilingual_prohibited_claims(phrase):
    assert failed(run_compliance(ci(inject(phrase)))).get("CMP-001") == "BLOCK"


def test_cautionary_mention_is_allowed():
    r = run_compliance(ci(inject("Beware of anyone promising guaranteed returns.")))
    assert "CMP-001" not in failed(r)


def test_missing_risk_warning_blocks():
    md = GOOD.replace(f"> **Risk warning:** {RISK_WARNINGS['en']}", "")
    assert failed(run_compliance(ci(md)))["CMP-002"] == "BLOCK"


def test_fabricated_citation_blocks():
    md = GOOD.replace("https://cybercrime.gov.in/ (", "https://totally-made-up.example/proof (")
    assert failed(run_compliance(ci(md)))["CMP-003"] == "BLOCK"


def test_missing_evidence_blocks():
    md = re.sub(r"\[\^\d+\]", "", GOOD.split("## Sources")[0])
    assert failed(run_compliance(ci(md)))["CMP-004"] == "BLOCK"


def test_unsupported_numeric_claim_needs_review():
    assert failed(run_compliance(ci(inject("Most traders lose 95% of their capital."))))["CMP-006"] == "REVIEW"


def test_uncited_regulatory_paragraph_needs_review():
    para = "RBI and SEBI have strict rules for every platform operating in India and they are enforced through FEMA every single day."
    md = GOOD.replace("## Frequently asked questions", f"{para}\n\n## Frequently asked questions")
    assert failed(run_compliance(ci(md)))["CMP-005"] == "REVIEW"


def test_fake_review_and_logo_block():
    f = failed(run_compliance(ci(inject("I made ₹50,000 in my first week. ![Exness logo](https://x.example/logo.png)"))))
    assert f["CMP-008"] == "BLOCK" and f["CMP-009"] == "BLOCK"


def test_solicitation_in_educational_content_blocks():
    assert failed(run_compliance(ci(inject("Open an account now and deposit today."))))["CMP-011"] == "BLOCK"


def test_promotional_content_with_unknown_authorization_is_not_publishable():
    r = run_compliance(ci(GOOD, content_class=ContentClass.PROMOTIONAL, content_type=ContentType.PROMOTIONAL))
    assert r.status in (ComplianceStatus.REVIEW, ComplianceStatus.BLOCK)
    assert r.publication_eligibility == PublicationEligibility.BLOCKED_PENDING_AUTHORIZATION


def test_promotional_not_authorized_blocks():
    r = run_compliance(ci(GOOD, content_class=ContentClass.PROMOTIONAL, content_type=ContentType.PROMOTIONAL,
                          authorization_status=AuthorizationStatus.NOT_AUTHORIZED))
    assert r.status == ComplianceStatus.BLOCK


def test_promotional_verified_can_be_eligible():
    r = run_compliance(ci(GOOD, content_class=ContentClass.PROMOTIONAL, content_type=ContentType.PROMOTIONAL,
                          authorization_status=AuthorizationStatus.VERIFIED))
    assert r.publication_eligibility == PublicationEligibility.ELIGIBLE_PROMOTIONAL


def test_misleading_rbi_endorsement_blocks():
    assert failed(run_compliance(ci(inject("Exness is RBI approved for Indians."))))["CMP-012"] == "BLOCK"


def test_superlative_about_broker_blocks():
    assert failed(run_compliance(ci(inject("Exness is the best broker for everyone."))))["CMP-013"] == "BLOCK"


def test_thin_content_blocks():
    md = (f"# T\n\n> **Risk warning:** {RISK_WARNINGS['en']}\n\nShort text.[^1]\n\n## Sources\n"
          "[^1]: x https://www.esma.europa.eu/node/84933\n")
    assert failed(run_compliance(ci(md)))["CMP-014"] == "BLOCK"


def test_duplicate_content_blocks():
    assert failed(run_compliance(ci(GOOD, other_articles={"older": GOOD})))["CMP-015"] == "BLOCK"


def test_repetitive_ai_text_needs_review():
    filler = " ".join(["In today's fast-paced world, let us delve into this seamless game-changer."] * 4)
    assert failed(run_compliance(ci(inject(filler))))["CMP-016"] == "REVIEW"


def test_adversarial_fixture_is_blocked_by_many_rules():
    md, _ = _render("bonus:exness")
    r = run_compliance(ci(md, content_class=ContentClass.PROMOTIONAL, content_type=ContentType.PROMOTIONAL))
    assert r.status == ComplianceStatus.BLOCK
    assert r.publication_eligibility == PublicationEligibility.BLOCKED
    assert {"CMP-001", "CMP-002", "CMP-003", "CMP-008", "CMP-009", "CMP-012", "CMP-013"} <= set(failed(r))


@pytest.mark.parametrize("intent_key,ctype", [
    ("regulation:generic", ContentType.GUIDE), ("withdrawal:generic", ContentType.TROUBLESHOOTING),
    ("login:exness", ContentType.TROUBLESHOOTING), ("fees:generic", ContentType.EXPLAINER),
])
def test_curated_educational_drafts_pass(intent_key, ctype):
    md, doc = _render(intent_key)
    r = run_compliance(ci(md, language=Language(doc["language"]), content_type=ctype))
    assert r.status == ComplianceStatus.PASS, failed(r)


@pytest.mark.parametrize("intent_key,ctype", [
    ("comparison:exness+xm", ContentType.COMPARISON), ("alternative:octafx", ContentType.ALTERNATIVES),
])
def test_named_third_party_content_routes_to_review(intent_key, ctype):
    md, doc = _render(intent_key)
    r = run_compliance(ci(md, language=Language(doc["language"]), content_type=ctype, named_entities=["exness"]))
    assert r.status == ComplianceStatus.REVIEW and "CMP-018" in failed(r)
