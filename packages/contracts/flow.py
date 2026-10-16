"""The ATLAS flow contract.

    SearchObservation
      -> KeywordCandidate
        -> Opportunity
          -> ContentPlan
            -> ContentBrief
              -> EvidenceBundle
                -> ArticleDraft
                  -> ComplianceReport
                    -> PublicationRecord

Each stage is a typed, validated Pydantic model. Domain logic consumes one
stage and produces the next; persistence stores them; workflows move them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.contracts.enums import (
    CannibalizationDecision,
    ComplianceStatus,
    ContentClass,
    ContentType,
    Language,
    PublicationEligibility,
    RetrievalMode,
    SearchIntent,
    Severity,
    SourceClass,
    SourceType,
    Theme,
    VerificationStatus,
)


class Contract(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="forbid")


# --------------------------------------------------------------------------- 1
class SearchObservation(Contract):
    """A single observed (or simulated) search query signal."""

    query: str = Field(min_length=2, max_length=300)
    language: Language
    locale: str
    source: str  # provider name, e.g. simulated_autocomplete, google_autocomplete, searxng
    source_type: SourceType
    confidence: float = Field(ge=0, le=1)
    observed_at: datetime
    demand_proxy: float | None = Field(default=None, ge=0, le=100, description="0-100 relative index; never absolute volume")
    trend_velocity: float | None = Field(default=None, ge=-1, le=5, description="relative change vs previous period")
    seed: str | None = None
    entity_keys: list[str] = Field(default_factory=list)
    is_news: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- 2
class KeywordCandidate(Contract):
    normalized_query: str
    display_query: str
    language: Language
    locale: str
    theme: Theme
    intent: SearchIntent
    entity_keys: list[str]
    intent_key: str  # language-agnostic canonical intent (theme + sorted entities)
    concept_tokens: list[str]
    demand_proxy: float | None
    trend_velocity: float | None
    source_types: list[SourceType]
    observation_count: int = 1
    is_news: bool = False
    first_seen: datetime | None = None
    is_new_today: bool = False


# --------------------------------------------------------------------------- SERP
class SerpResult(Contract):
    position: int
    url: str
    title: str
    domain: str
    snippet: str = ""
    page_type: str = "article"  # article | forum | broker_official | video | news | regulator | directory
    published: str | None = None
    word_count_estimate: int | None = None
    has_faq: bool = False
    headings: list[str] = Field(default_factory=list)
    authority_proxy: float | None = Field(default=None, ge=0, le=1)
    intent_match: float | None = Field(default=None, ge=0, le=1)


class SerpSnapshot(Contract):
    query: str
    language: Language
    captured_at: datetime
    source: str
    source_type: SourceType
    results: list[SerpResult]


class SerpAnalysis(Contract):
    weakness: float = Field(ge=0, le=100)
    competition_proxy: float = Field(ge=0, le=100)
    avg_intent_match: float
    forum_share: float
    stale_share: float
    faq_share: float
    avg_word_count: int | None
    content_gaps: list[str]
    notes: list[str]
    source_type: SourceType


# --------------------------------------------------------------------------- 3
class ScoreComponent(Contract):
    key: str
    label: str
    value: float  # normalised 0-100
    weight: float  # contribution weight (negative for penalties)
    contribution: float
    source_type: SourceType
    explanation: str


class CannibalizationCheck(Contract):
    check: str  # intent_key | keyword_overlap | semantic | serp_overlap | slug
    score: float
    threshold: float
    triggered: bool
    against_article_id: UUID | None = None
    against_opportunity_id: UUID | None = None
    against_label: str | None = None
    detail: str


class CannibalizationResult(Contract):
    decision: CannibalizationDecision
    reason: str
    conflicting_article_id: UUID | None = None
    conflicting_opportunity_id: UUID | None = None
    checks: list[CannibalizationCheck]


class Opportunity(Contract):
    candidate: KeywordCandidate
    score: float
    components: list[ScoreComponent]
    why: list[str]
    content_type: ContentType
    content_class: ContentClass
    serp: SerpAnalysis | None = None
    cannibalization: CannibalizationResult | None = None


# --------------------------------------------------------------------------- 4/5
class OutlineSection(Contract):
    heading: str
    level: int = Field(default=2, ge=2, le=3)
    purpose: str
    evidence_keys: list[str] = Field(default_factory=list)


class InternalLinkSuggestion(Contract):
    target_article_id: UUID
    target_slug: str
    target_title: str
    anchor_text: str
    score: float
    reason: str


class ContentBrief(Contract):
    target_keyword: str
    secondary_keywords: list[str]
    language: Language
    locale: str
    hreflang: str
    search_intent: SearchIntent
    content_type: ContentType
    content_class: ContentClass
    recommended_title: str
    slug: str
    angle: str
    audience: str
    outline: list[OutlineSection]
    questions_to_answer: list[str]
    sources_required: list[str]
    internal_links: list[InternalLinkSuggestion]
    compliance_considerations: list[str]
    cta_policy: str
    schema_recommendations: list[str]
    entity_keys: list[str]
    intent_key: str
    theme: Theme

    @field_validator("slug")
    @classmethod
    def slug_is_safe(cls, v: str) -> str:
        import re

        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", v):
            raise ValueError("slug must be lowercase ascii words separated by hyphens")
        return v


class ContentPlan(Contract):
    plan_date: str
    sim_day: int | None
    selected: list[UUID]
    rejected: list[UUID]
    rationale: list[str]


# --------------------------------------------------------------------------- 6
class EvidenceClaimItem(Contract):
    key: str
    claim: str
    claim_type: str  # regulation | statistic | enforcement | process | definition | broker_property
    confidence: float = Field(ge=0, le=1)
    verification_status: VerificationStatus


class EvidenceItem(Contract):
    key: str
    url: str
    title: str
    publisher: str
    source_type: SourceType
    source_class: SourceClass
    retrieval_mode: RetrievalMode
    retrieved_at: datetime
    published_at: str | None = None
    snippet: str
    language: str = "en"
    claims: list[EvidenceClaimItem]
    tags: list[str] = Field(default_factory=list)


class EvidenceBundle(Contract):
    brief_intent_key: str
    items: list[EvidenceItem]
    gaps: list[str]  # facts the brief wanted but could not be evidenced -> omitted / labelled
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- 7
class FAQItem(Contract):
    question: str
    answer: str


class ComparisonRow(Contract):
    dimension: str
    values: list[str]
    verification: str  # e.g. VERIFIED_SNAPSHOT | UNVERIFIED | METHOD


class ComparisonTable(Contract):
    caption: str
    columns: list[str]
    rows: list[ComparisonRow]


class DraftSection(Contract):
    heading: str
    level: int = Field(default=2, ge=2, le=3)
    body: str = Field(min_length=20)


class LLMArticlePayload(Contract):
    """The structured output an LLM (or the demo provider) must return. Validated + retried."""

    title: str = Field(min_length=10, max_length=120)
    meta_description: str = Field(min_length=50, max_length=170)
    h1: str = Field(min_length=10, max_length=140)
    introduction: str = Field(min_length=80)
    sections: list[DraftSection] = Field(min_length=3)
    table: ComparisonTable | None = None
    faq: list[FAQItem] = Field(min_length=3)
    key_takeaways: list[str] = Field(default_factory=list)


class ArticleDraft(Contract):
    brief: ContentBrief
    payload: LLMArticlePayload
    markdown: str
    frontmatter: dict[str, Any]
    seo: dict[str, Any]
    word_count: int
    generator: str
    used_evidence_keys: list[str]
    internal_links: list[InternalLinkSuggestion]


# --------------------------------------------------------------------------- 8
class RuleResult(Contract):
    rule_id: str
    name: str
    category: str
    severity_on_fail: Severity
    passed: bool
    outcome: Severity | None  # None when passed
    message: str
    evidence: list[str] = Field(default_factory=list)  # offending snippets


class ComplianceReport(Contract):
    status: ComplianceStatus
    publication_eligibility: PublicationEligibility
    content_class: ContentClass
    rule_results: list[RuleResult]
    reasons: list[str]
    llm_advisory: dict[str, Any] | None = None
    deterministic_authoritative: bool = True


# --------------------------------------------------------------------------- 9
class PublicationRecord(Contract):
    article_id: UUID
    version: int
    slug: str
    compliance_status: ComplianceStatus
    publication_eligibility: PublicationEligibility
    file_path: str
    recorded_at: datetime
