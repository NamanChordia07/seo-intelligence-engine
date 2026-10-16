"""API response / request schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    temporal: str
    orchestrator: str
    provider_mode: str
    llm_provider: str
    version: str


class StepOut(ORM):
    id: UUID
    name: str
    status: str
    attempts: int
    started_at: datetime
    finished_at: datetime | None
    detail: dict[str, Any]
    error: str | None


class RunOut(ORM):
    id: UUID
    parent_run_id: UUID | None
    kind: str
    sim_day: int | None
    plan_date: str | None
    status: str
    orchestrator: str
    temporal_workflow_id: str | None
    provider_mode: str
    trigger: str
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    stats: dict[str, Any]
    created_at: datetime


class RunDetail(RunOut):
    steps: list[StepOut]
    children: list[RunOut] = Field(default_factory=list)


class RunCreate(BaseModel):
    kind: Literal["DAILY_INTELLIGENCE", "DEMO_SIMULATION"] = "DAILY_INTELLIGENCE"
    sim_day: int | None = Field(default=None, ge=1, le=30)
    force: bool = False
    wait: bool = False


class OpportunityOut(ORM):
    id: UUID
    run_id: UUID
    candidate_id: UUID
    sim_day: int | None
    intent_key: str
    keyword: str
    language: str
    locale: str
    theme: str
    intent: str
    content_type: str
    content_class: str
    score: float
    components: list[dict[str, Any]]
    why: list[str]
    status: str
    status_reason: str | None
    cannibalization: dict[str, Any]
    conflicting_article_id: UUID | None
    rank: int | None
    article_id: UUID | None
    created_at: datetime


class ArticleSummary(ORM):
    id: UUID
    origin: str
    sim_day: int | None
    slug: str
    title: str
    target_keyword: str
    language: str
    locale: str
    theme: str
    intent: str
    intent_key: str
    content_type: str
    content_class: str
    status: str
    compliance_status: str
    publication_eligibility: str
    current_version: int
    opportunity_score: float | None
    is_test_fixture: bool
    file_path: str | None
    created_at: datetime
    updated_at: datetime


class ApproveIn(BaseModel):
    reviewer: str = Field(min_length=2, max_length=80, pattern=r"^[\w .@-]+$")
    note: str = Field(min_length=3, max_length=1000)


class ComplianceCheckIn(BaseModel):
    markdown: str = Field(min_length=20, max_length=200_000)
    language: Literal["en", "hi", "hi-Latn"] = "en"
    content_class: Literal["EDUCATIONAL", "PROMOTIONAL"] = "EDUCATIONAL"
    content_type: str = "guide"


class SettingsPatch(BaseModel):
    india_authorization_status: Literal["UNKNOWN", "VERIFIED", "NOT_AUTHORIZED"] | None = None
    max_pages_per_day: int | None = Field(default=None, ge=1, le=5)
    actor: str = Field(default="demo-user", max_length=80, pattern=r"^[\w .@-]+$")
