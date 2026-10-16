"""Centralised settings (environment variables only - no secrets in code)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT_DIR / "data" / "fixtures"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_", env_file=ROOT_DIR / ".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://atlas@127.0.0.1:5433/atlas"
    test_database_url: str = "postgresql+psycopg://atlas@127.0.0.1:5433/atlas_test"

    orchestrator: str = "auto"  # temporal | inline | auto
    temporal_address: str = "127.0.0.1:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "atlas-main"
    temporal_ui_url: str = "http://127.0.0.1:8233"

    provider_mode: str = "demo"  # demo | hybrid | live
    searxng_url: str = ""
    live_research: bool = False
    autocomplete_budget: int = 40  # live runs: public autocomplete calls per day (seeds rotate across days)
    live_news: bool = True  # live runs: Google Trends India RSS + Google News RSS
    live_broker_demand: bool = True  # live runs: measure the broker demand index before discovery

    # Daily schedule (Temporal Schedule). Cron is evaluated in schedule_timezone.
    schedule_cron: str = "0 6 * * *"
    schedule_timezone: str = "Asia/Kolkata"

    llm_provider: str = "demo"  # demo | ollama | openai
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "llama3.2:3b"
    llm_api_key: str = ""
    llm_advisory_review: bool = False

    output_dir: str = "outputs/articles"
    site_dir: str = "outputs/site"  # static, publish-ready HTML build (eligible pages only)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Demo calendar: simulated Day 1 = demo_base_date
    demo_base_date: str = "2026-10-14"
    max_pages_per_day: int = 3
    min_pages_per_day: int = 2
    selection_threshold: float = 45.0

    @property
    def output_path(self) -> Path:
        p = Path(self.output_dir)
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def site_path(self) -> Path:
        p = Path(self.site_dir)
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
