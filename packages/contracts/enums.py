"""Shared enumerations. String enums so they serialise cleanly to JSON / Postgres."""

from __future__ import annotations

from enum import StrEnum


class SourceType(StrEnum):
    """Provenance of every signal. Simulated values are never presented as real."""

    REAL_PUBLIC = "REAL_PUBLIC"  # observed from a real public source
    PROXY = "PROXY"  # derived/heuristic estimate from real observations
    SIMULATED = "SIMULATED"  # deterministic demonstration data


class RetrievalMode(StrEnum):
    LIVE_FETCH = "LIVE_FETCH"  # fetched during this run
    FIXTURE_SNAPSHOT = "FIXTURE_SNAPSHOT"  # curated snapshot of a real public document (verify live before publishing)
    SIMULATED = "SIMULATED"


class SourceClass(StrEnum):
    PRIMARY_REGULATOR = "PRIMARY_REGULATOR"
    OFFICIAL_GOVERNMENT = "OFFICIAL_GOVERNMENT"
    EXCHANGE = "EXCHANGE"
    SECONDARY_MEDIA = "SECONDARY_MEDIA"
    EDUCATIONAL_REFERENCE = "EDUCATIONAL_REFERENCE"
    THIRD_PARTY_DIRECTORY = "THIRD_PARTY_DIRECTORY"
    BROKER_OFFICIAL = "BROKER_OFFICIAL"


class Language(StrEnum):
    EN = "en"
    HI = "hi"  # Hindi, Devanagari script
    HINGLISH = "hi-Latn"  # Hindi written in Latin script / code-mixed


class Theme(StrEnum):
    REVIEW = "review"
    ALTERNATIVE = "alternative"
    COMPARISON = "comparison"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    APP = "app"
    BONUS = "bonus"
    LOGIN = "login"
    FEES = "fees"  # fees + spreads + swaps = trading costs
    REGULATION = "regulation"
    ACCOUNT = "account"
    TRADING_ISSUES = "trading_issues"
    LEVERAGE = "leverage"
    SUPPORT = "support"
    NEWS = "news"
    BASICS = "basics"


class SearchIntent(StrEnum):
    INFORMATIONAL = "informational"
    COMMERCIAL_INVESTIGATION = "commercial_investigation"
    TRANSACTIONAL = "transactional"
    NAVIGATIONAL = "navigational"
    TROUBLESHOOTING = "troubleshooting"


class ContentType(StrEnum):
    GUIDE = "guide"
    COMPARISON = "comparison"
    ALTERNATIVES = "alternatives"
    TROUBLESHOOTING = "troubleshooting"
    EXPLAINER = "explainer"
    NEWS_ANALYSIS = "news_analysis"
    PROMOTIONAL = "promotional"


class ContentClass(StrEnum):
    EDUCATIONAL = "EDUCATIONAL"
    PROMOTIONAL = "PROMOTIONAL"


class AuthorizationStatus(StrEnum):
    """Is the target platform verified as authorised to solicit Indian residents?"""

    UNKNOWN = "UNKNOWN"
    VERIFIED = "VERIFIED"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


class OpportunityStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"  # duplicate / cannibalising / below threshold
    UPDATE_EXISTING = "UPDATE_EXISTING"  # recommend refreshing an existing page instead
    LOCALE_VARIANT = "LOCALE_VARIANT"  # same intent, other language -> hreflang alternate later
    DEFERRED = "DEFERRED"  # eligible but capacity reached today


class CannibalizationDecision(StrEnum):
    NEW_PAGE_OK = "NEW_PAGE_OK"
    REJECT_NEW_PAGE = "REJECT_NEW_PAGE"
    UPDATE_EXISTING_PAGE = "UPDATE_EXISTING_PAGE"
    LOCALE_VARIANT = "LOCALE_VARIANT"


class ComplianceStatus(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"
    PENDING = "PENDING"


class PublicationEligibility(StrEnum):
    ELIGIBLE_EDUCATIONAL = "ELIGIBLE_EDUCATIONAL"
    ELIGIBLE_PROMOTIONAL = "ELIGIBLE_PROMOTIONAL"
    REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"
    BLOCKED_PENDING_AUTHORIZATION = "BLOCKED_PENDING_AUTHORIZATION"
    BLOCKED = "BLOCKED"


class ArticleStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    PUBLISHED = "PUBLISHED"  # used only for pre-existing simulated site inventory


class ArticleOrigin(StrEnum):
    GENERATED = "GENERATED"
    INVENTORY = "INVENTORY"  # pre-existing site page (simulated inventory)


class RunKind(StrEnum):
    DAILY_INTELLIGENCE = "DAILY_INTELLIGENCE"
    ARTICLE_GENERATION = "ARTICLE_GENERATION"
    DEMO_SIMULATION = "DEMO_SIMULATION"
    LIVE_PROBE = "LIVE_PROBE"
    VALIDATION = "VALIDATION"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class StepStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class Severity(StrEnum):
    INFO = "INFO"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class VerificationStatus(StrEnum):
    VERIFIED_LIVE = "VERIFIED_LIVE"
    VERIFIED_SNAPSHOT = "VERIFIED_SNAPSHOT"  # supported by a curated snapshot of a real public document
    UNVERIFIED = "UNVERIFIED"
    CONFLICTING = "CONFLICTING"
