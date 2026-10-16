"""Shared helpers for activities: provider selection + project context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from packages.config import get_settings
from packages.contracts.enums import AuthorizationStatus
from packages.persistence.models import Project, WorkflowRun
from packages.providers.fixtures import day_config
from packages.providers.live import GoogleAutocompleteProvider, SafeHttpExtractor, SearxngSerpProvider
from packages.providers.simulated import (
    FixtureEvidenceProvider,
    FixtureSerpProvider,
    SimulatedSuggestionProvider,
    SimulatedTrendProvider,
)


@dataclass
class RunContext:
    run: WorkflowRun
    project: Project
    sim_day: int | None
    plan_date: date
    is_simulated: bool

    @property
    def settings(self) -> dict[str, Any]:
        return self.project.settings or {}

    @property
    def authorization(self) -> AuthorizationStatus:
        return AuthorizationStatus(self.settings.get("india_authorization_status", "UNKNOWN"))

    @property
    def max_pages(self) -> int:
        return int(self.settings.get("max_pages_per_day", get_settings().max_pages_per_day))


def run_context(session: Session, run: WorkflowRun) -> RunContext:
    project = session.get(Project, run.project_id)
    assert project is not None
    if run.sim_day is not None:
        plan_date = date.fromisoformat(day_config(run.sim_day)["date"])
    else:
        plan_date = date.fromisoformat(run.plan_date) if run.plan_date else date.today()
    return RunContext(run=run, project=project, sim_day=run.sim_day, plan_date=plan_date, is_simulated=run.sim_day is not None)


def suggestion_providers(ctx: RunContext) -> list[Any]:
    if ctx.is_simulated:
        return [SimulatedSuggestionProvider()]
    return [GoogleAutocompleteProvider()]


def trend_providers(ctx: RunContext) -> list[Any]:
    return [SimulatedTrendProvider()] if ctx.is_simulated else []


def serp_provider(ctx: RunContext) -> Any:
    url = get_settings().searxng_url
    if not ctx.is_simulated and url:
        return SearxngSerpProvider(url)
    return FixtureSerpProvider()


def evidence_provider() -> FixtureEvidenceProvider:
    return FixtureEvidenceProvider()


def extractor() -> SafeHttpExtractor:
    return SafeHttpExtractor()
