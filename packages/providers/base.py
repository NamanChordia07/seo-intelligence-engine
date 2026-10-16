"""Provider interfaces. Business logic depends only on these protocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from packages.contracts.enums import Language
from packages.contracts.flow import ContentBrief, EvidenceItem, LLMArticlePayload, SearchObservation, SerpSnapshot
from packages.domain.discovery import SeedQuery


class ProviderUnavailable(RuntimeError):
    """External provider failed / rate-limited / disabled. Callers must degrade gracefully."""


class LLMOutputError(RuntimeError):
    """Model output could not be validated against the contract after retries."""


class SearchSuggestionProvider(Protocol):
    name: str

    def suggest(self, seed: SeedQuery, sim_day: int | None) -> list[SearchObservation]: ...


class TrendProvider(Protocol):
    name: str

    def rising(self, sim_day: int | None, languages: list[Language]) -> list[SearchObservation]: ...


class SerpProvider(Protocol):
    name: str

    def serp(self, query: str, language: Language, intent_key: str) -> SerpSnapshot: ...


@dataclass
class ExtractedPage:
    url: str
    status: int
    title: str = ""
    headings: list[str] = field(default_factory=list)
    text: str = ""
    word_count: int = 0
    error: str | None = None


class PageExtractionProvider(Protocol):
    name: str

    def extract(self, url: str) -> ExtractedPage: ...


class EvidenceProvider(Protocol):
    name: str

    def find(self, tags: list[str], entity_keys: list[str]) -> list[EvidenceItem]: ...


@dataclass
class GenerationContext:
    evidence: list[EvidenceItem]
    internal_link_targets: list[dict[str, Any]]  # {intent_key, title, slug, anchor}
    plan_date: str


class LLMProvider(Protocol):
    name: str

    def generate_article(self, brief: ContentBrief, ctx: GenerationContext) -> LLMArticlePayload: ...

    def complete_json(self, system: str, user: str) -> dict[str, Any]: ...
