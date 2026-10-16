"""SQLAlchemy ORM models. PostgreSQL is the system of record.

Key integrity guarantees enforced by the database (not by an LLM):

* ``uq_reservation_project_intent``  - one canonical intent can only ever be reserved once per project
* ``uq_article_project_slug``        - no duplicate slugs
* ``uq_candidate_project_query_lang``- no duplicate keyword candidates
* ``uq_internal_link_pair``          - no duplicate internal links
* ``uq_article_version``             - monotonically versioned article bodies
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 256


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def fk(target: str, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped[Any]:
    return mapped_column(UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# --------------------------------------------------------------------------- tenancy
class Tenant(Timestamped, Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)


class Project(Timestamped, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_project_tenant_slug"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = fk("tenants.id")
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100))
    domain: Mapped[str] = mapped_column(String(255))
    default_locale: Mapped[str] = mapped_column(String(20), default="en-IN")
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Entity(Timestamped, Base):
    """Tracked broker / topic / regulator."""

    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_entity_project_key"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))  # BROKER | TOPIC | REGULATOR
    aliases: Mapped[list[Any]] = mapped_column(default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    tracked: Mapped[bool] = mapped_column(Boolean, default=True)


# --------------------------------------------------------------------------- workflow + audit
class WorkflowRun(Timestamped, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (Index("ix_run_project_day", "project_id", "sim_day"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    parent_run_id: Mapped[uuid.UUID | None] = fk("workflow_runs.id", nullable=True, ondelete="SET NULL")
    kind: Mapped[str] = mapped_column(String(40))
    sim_day: Mapped[int | None] = mapped_column(Integer)
    plan_date: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    orchestrator: Mapped[str] = mapped_column(String(20), default="inline")
    temporal_workflow_id: Mapped[str | None] = mapped_column(String(200))
    provider_mode: Mapped[str] = mapped_column(String(20), default="demo")
    trigger: Mapped[str] = mapped_column(String(40), default="api")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict)
    steps: Mapped[list[WorkflowStep]] = relationship(
        back_populates="run", order_by="WorkflowStep.started_at", cascade="all, delete-orphan"
    )


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (UniqueConstraint("run_id", "name", name="uq_step_run_name"),)
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID] = fk("workflow_runs.id")
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    run: Mapped[WorkflowRun] = relationship(back_populates="steps")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_project_created", "project_id", "created_at"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[uuid.UUID | None] = fk("workflow_runs.id", nullable=True, ondelete="SET NULL")
    article_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(80), default="system")
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- discovery
class SearchObservationRow(Base):
    __tablename__ = "search_observations"
    __table_args__ = (
        Index("ix_obs_project_day", "project_id", "sim_day"),
        Index("ix_obs_project_query", "project_id", "normalized_query"),
    )
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[uuid.UUID | None] = fk("workflow_runs.id", nullable=True, ondelete="SET NULL")
    sim_day: Mapped[int | None] = mapped_column(Integer)
    query: Mapped[str] = mapped_column(String(300))
    normalized_query: Mapped[str] = mapped_column(String(300))
    language: Mapped[str] = mapped_column(String(10), index=True)
    locale: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(80))
    source_type: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    demand_proxy: Mapped[float | None] = mapped_column(Float)
    trend_velocity: Mapped[float | None] = mapped_column(Float)
    seed: Mapped[str | None] = mapped_column(String(200))
    entity_keys: Mapped[list[Any]] = mapped_column(default=list)
    is_news: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntentCluster(Timestamped, Base):
    __tablename__ = "intent_clusters"
    __table_args__ = (UniqueConstraint("project_id", "intent_key", name="uq_cluster_project_intent"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    intent_key: Mapped[str] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(300))
    theme: Mapped[str] = mapped_column(String(40))
    intent: Mapped[str] = mapped_column(String(40))
    entity_keys: Mapped[list[Any]] = mapped_column(default=list)
    languages: Mapped[list[Any]] = mapped_column(default=list)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)


class KeywordCandidateRow(Timestamped, Base):
    __tablename__ = "keyword_candidates"
    __table_args__ = (
        UniqueConstraint("project_id", "normalized_query", "language", name="uq_candidate_project_query_lang"),
    )
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    cluster_id: Mapped[uuid.UUID | None] = fk("intent_clusters.id", nullable=True, ondelete="SET NULL")
    normalized_query: Mapped[str] = mapped_column(String(300))
    display_query: Mapped[str] = mapped_column(String(300))
    language: Mapped[str] = mapped_column(String(10))
    locale: Mapped[str] = mapped_column(String(20))
    theme: Mapped[str] = mapped_column(String(40), index=True)
    intent: Mapped[str] = mapped_column(String(40))
    entity_keys: Mapped[list[Any]] = mapped_column(default=list)
    intent_key: Mapped[str] = mapped_column(String(200), index=True)
    concept_tokens: Mapped[list[Any]] = mapped_column(default=list)
    demand_proxy: Mapped[float | None] = mapped_column(Float)
    trend_velocity: Mapped[float | None] = mapped_column(Float)
    source_types: Mapped[list[Any]] = mapped_column(default=list)
    observation_count: Mapped[int] = mapped_column(Integer, default=1)
    is_news: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_day: Mapped[int | None] = mapped_column(Integer)
    last_seen_day: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)


class SerpSnapshotRow(Base):
    __tablename__ = "serp_snapshots"
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[uuid.UUID | None] = fk("workflow_runs.id", nullable=True, ondelete="SET NULL")
    candidate_id: Mapped[uuid.UUID | None] = fk("keyword_candidates.id", nullable=True)
    query: Mapped[str] = mapped_column(String(300))
    language: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(80))
    source_type: Mapped[str] = mapped_column(String(20))
    results: Mapped[list[Any]] = mapped_column(default=list)
    analysis: Mapped[dict[str, Any]] = mapped_column(default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OpportunityRow(Timestamped, Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("run_id", "candidate_id", name="uq_opportunity_run_candidate"),
        Index("ix_opp_project_status", "project_id", "status"),
    )
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[uuid.UUID] = fk("workflow_runs.id")
    candidate_id: Mapped[uuid.UUID] = fk("keyword_candidates.id")
    sim_day: Mapped[int | None] = mapped_column(Integer)
    intent_key: Mapped[str] = mapped_column(String(200), index=True)
    keyword: Mapped[str] = mapped_column(String(300))
    language: Mapped[str] = mapped_column(String(10))
    locale: Mapped[str] = mapped_column(String(20))
    theme: Mapped[str] = mapped_column(String(40))
    intent: Mapped[str] = mapped_column(String(40))
    content_type: Mapped[str] = mapped_column(String(40))
    content_class: Mapped[str] = mapped_column(String(20))
    score: Mapped[float] = mapped_column(Float, index=True)
    components: Mapped[list[Any]] = mapped_column(default=list)
    why: Mapped[list[Any]] = mapped_column(default=list)
    serp_analysis: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(30), default="CANDIDATE")
    status_reason: Mapped[str | None] = mapped_column(Text)
    cannibalization: Mapped[dict[str, Any]] = mapped_column(default=dict)
    conflicting_article_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    rank: Mapped[int | None] = mapped_column(Integer)
    article_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class IntentReservation(Base):
    """Database-enforced guarantee: an intent is scheduled at most once per project."""

    __tablename__ = "intent_reservations"
    __table_args__ = (UniqueConstraint("project_id", "intent_key", name="uq_reservation_project_intent"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    intent_key: Mapped[str] = mapped_column(String(200))
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    article_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentPlanRow(Base):
    __tablename__ = "content_plans"
    __table_args__ = (UniqueConstraint("run_id", name="uq_plan_run"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[uuid.UUID] = fk("workflow_runs.id")
    plan_date: Mapped[str] = mapped_column(String(10))
    sim_day: Mapped[int | None] = mapped_column(Integer)
    selected_opportunity_ids: Mapped[list[Any]] = mapped_column(default=list)
    rejected_opportunity_ids: Mapped[list[Any]] = mapped_column(default=list)
    rationale: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentBriefRow(Base):
    __tablename__ = "content_briefs"
    __table_args__ = (UniqueConstraint("opportunity_id", name="uq_brief_opportunity"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    opportunity_id: Mapped[uuid.UUID] = fk("opportunities.id")
    brief: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- evidence
class EvidenceSource(Base):
    __tablename__ = "evidence_sources"
    __table_args__ = (UniqueConstraint("project_id", "url", name="uq_evidence_project_url"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    key: Mapped[str] = mapped_column(String(120), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(String(500))
    publisher: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(20))
    source_class: Mapped[str] = mapped_column(String(40))
    retrieval_mode: Mapped[str] = mapped_column(String(30))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[str | None] = mapped_column(String(40))
    snippet: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    live_status: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceClaim(Base):
    __tablename__ = "evidence_claims"
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    source_id: Mapped[uuid.UUID] = fk("evidence_sources.id")
    article_id: Mapped[uuid.UUID | None] = fk("articles.id", nullable=True)
    claim_key: Mapped[str] = mapped_column(String(120))
    claim_text: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float)
    verification_status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------- content
class Article(Timestamped, Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_article_project_slug"),
        Index("ix_article_project_status", "project_id", "status"),
    )
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    run_id: Mapped[uuid.UUID | None] = fk("workflow_runs.id", nullable=True, ondelete="SET NULL")
    origin: Mapped[str] = mapped_column(String(20), default="GENERATED")
    sim_day: Mapped[int | None] = mapped_column(Integer)
    slug: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    target_keyword: Mapped[str] = mapped_column(String(300))
    language: Mapped[str] = mapped_column(String(10))
    locale: Mapped[str] = mapped_column(String(20))
    theme: Mapped[str] = mapped_column(String(40))
    intent: Mapped[str] = mapped_column(String(40))
    intent_key: Mapped[str] = mapped_column(String(200), index=True)
    entity_keys: Mapped[list[Any]] = mapped_column(default=list)
    content_type: Mapped[str] = mapped_column(String(40))
    content_class: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    compliance_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    publication_eligibility: Mapped[str] = mapped_column(String(40), default="REQUIRES_HUMAN_REVIEW")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    file_path: Mapped[str | None] = mapped_column(String(500))
    is_test_fixture: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    versions: Mapped[list[ArticleVersion]] = relationship(
        back_populates="article", order_by="ArticleVersion.version", cascade="all, delete-orphan"
    )


class ArticleVersion(Base):
    __tablename__ = "article_versions"
    __table_args__ = (UniqueConstraint("article_id", "version", name="uq_article_version"),)
    id: Mapped[uuid.UUID] = pk()
    article_id: Mapped[uuid.UUID] = fk("articles.id")
    version: Mapped[int] = mapped_column(Integer)
    markdown: Mapped[str] = mapped_column(Text)
    frontmatter: Mapped[dict[str, Any]] = mapped_column(default=dict)
    seo: Mapped[dict[str, Any]] = mapped_column(default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    brief: Mapped[dict[str, Any]] = mapped_column(default=dict)
    word_count: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    generator: Mapped[str] = mapped_column(String(120))
    change_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    article: Mapped[Article] = relationship(back_populates="versions")


class ComplianceDecision(Base):
    __tablename__ = "compliance_decisions"
    __table_args__ = (Index("ix_compliance_article", "article_id", "created_at"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    article_id: Mapped[uuid.UUID | None] = fk("articles.id", nullable=True)
    article_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    publication_eligibility: Mapped[str] = mapped_column(String(40))
    content_class: Mapped[str] = mapped_column(String(20))
    rule_results: Mapped[list[Any]] = mapped_column(default=list)
    reasons: Mapped[list[Any]] = mapped_column(default=list)
    llm_advisory: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    decided_by: Mapped[str] = mapped_column(String(80), default="policy-engine")
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InternalLink(Base):
    __tablename__ = "internal_links"
    __table_args__ = (UniqueConstraint("source_article_id", "target_article_id", name="uq_internal_link_pair"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    source_article_id: Mapped[uuid.UUID] = fk("articles.id")
    target_article_id: Mapped[uuid.UUID] = fk("articles.id")
    anchor_text: Mapped[str] = mapped_column(String(300))
    score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(30))  # INSERTED | REVERSE_SUGGESTED
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LedgerEntry(Base):
    """Append-only running sheet. One row per meaningful content decision."""

    __tablename__ = "content_ledger"
    __table_args__ = (Index("ix_ledger_project_created", "project_id", "created_at"),)
    id: Mapped[uuid.UUID] = pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    entry_type: Mapped[str] = mapped_column(String(40))  # ARTICLE_CREATED | COMPLIANCE_UPDATED | APPROVED | OPPORTUNITY_REJECTED ...
    plan_date: Mapped[str | None] = mapped_column(String(10))
    sim_day: Mapped[int | None] = mapped_column(Integer)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    article_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    target_keyword: Mapped[str] = mapped_column(String(300))
    language: Mapped[str] = mapped_column(String(10))
    locale: Mapped[str | None] = mapped_column(String(20))
    intent: Mapped[str | None] = mapped_column(String(40))
    intent_key: Mapped[str | None] = mapped_column(String(200))
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    target_slug: Mapped[str | None] = mapped_column(String(200))
    content_status: Mapped[str | None] = mapped_column(String(30))
    compliance_status: Mapped[str | None] = mapped_column(String(20))
    publication_eligibility: Mapped[str | None] = mapped_column(String(40))
    workflow_status: Mapped[str | None] = mapped_column(String(20))
    evidence_sources: Mapped[list[Any]] = mapped_column(default=list)
    article_version: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
