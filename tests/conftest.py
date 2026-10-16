"""Test configuration: integration tests run against the isolated `atlas_test` database."""

from __future__ import annotations

import os
from pathlib import Path

_dotenv = Path(__file__).resolve().parents[1] / ".env"
if _dotenv.exists():
    for _line in _dotenv.read_text(encoding="utf-8").splitlines():
        _k, _sep, _v = _line.strip().partition("=")
        if _sep and _k == "ATLAS_TEST_DATABASE_URL":
            os.environ.setdefault(_k, _v.strip())
os.environ.setdefault("ATLAS_TEST_DATABASE_URL", "postgresql+psycopg://atlas@127.0.0.1:5433/atlas_test")
os.environ["ATLAS_DATABASE_URL"] = os.environ["ATLAS_TEST_DATABASE_URL"]
os.environ["ATLAS_ORCHESTRATOR"] = "inline"
os.environ["ATLAS_PROVIDER_MODE"] = "demo"
os.environ["ATLAS_LLM_PROVIDER"] = "demo"
os.environ["ATLAS_LIVE_RESEARCH"] = "false"
os.environ["ATLAS_OUTPUT_DIR"] = ".data/test-output/articles"

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from packages.config import get_settings  # noqa: E402

get_settings.cache_clear()


def _db_available() -> bool:
    try:
        from packages.persistence.db import get_engine

        with get_engine().connect() as c:
            c.execute(text("select 1"))
            return c.execute(text("select count(*) from information_schema.tables where table_name='articles'")).scalar() == 1
    except Exception:  # noqa: BLE001
        return False


DB_OK = _db_available()


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason="PostgreSQL test database unavailable (run scripts/devstack.py up + alembic upgrade)")
    for item in items:
        if "integration" in str(item.fspath) and not DB_OK:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def demo_world():
    """Reset the test DB and run simulated Day 1-3 inline once for the whole session."""
    from packages.persistence.db import session_scope
    from packages.persistence.models import WorkflowRun
    from packages.persistence.repositories import get_default_project, reset_project_data
    from packages.persistence.seed import seed_inventory
    from packages.providers.fixtures import day_config
    from workflows.engine import run_daily_inline

    with session_scope() as s:
        p = get_default_project(s)
        reset_project_data(s, p.id)
        seed_inventory(s, p)
        settings = dict(p.settings or {})
        settings["india_authorization_status"] = "UNKNOWN"
        p.settings = settings
        pid = p.id
    runs = {}
    for day in (1, 2, 3):
        with session_scope() as s:
            r = WorkflowRun(project_id=pid, kind="DAILY_INTELLIGENCE", sim_day=day, plan_date=day_config(day)["date"],
                            status="QUEUED", orchestrator="inline")
            s.add(r)
            s.flush()
            runs[day] = str(r.id)
        runs[f"stats{day}"] = run_daily_inline(runs[day])
    return {"project_id": pid, "runs": runs}
