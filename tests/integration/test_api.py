"""API tests (FastAPI TestClient) on top of the simulated Day 1-3 world."""

import csv
import io

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app


@pytest.fixture(scope="module")
def client(demo_world):
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["database"] is True


def test_dashboard_counts(client):
    d = client.get("/api/v1/dashboard").json()
    assert d["counts"]["articles_generated"] >= 6
    assert d["compliance"]["BLOCK"] >= 1
    assert {"en", "hi", "hi-Latn"} <= set(d["articles_by_language"])
    assert all(day["status"] in ("COMPLETED", "PARTIAL") for day in d["days"])


def test_observations_are_labelled_simulated(client):
    rows = client.get("/api/v1/observations").json()
    assert rows and {r["source_type"] for r in rows} == {"SIMULATED"}


def test_opportunity_detail_has_breakdown(client):
    opp = client.get("/api/v1/opportunities", params={"status": "SELECTED"}).json()[0]
    d = client.get(f"/api/v1/opportunities/{opp['id']}").json()
    assert d["opportunity"]["components"] and d["opportunity"]["why"]
    assert d["serp"]["source_type"] == "SIMULATED" and d["brief"]["slug"]


def test_article_render_and_evidence(client):
    arts = client.get("/api/v1/articles", params={"origin": "GENERATED", "include_test": False}).json()
    a = arts[0]
    d = client.get(f"/api/v1/articles/{a['id']}").json()
    assert d["version"]["markdown"].startswith("---") and d["version"]["seo"]["hreflang"]
    ev = client.get(f"/api/v1/articles/{a['id']}/evidence").json()
    assert len(ev["sources"]) >= 2 and all(s["url"].startswith("https://") for s in ev["sources"])
    md = client.get(f"/api/v1/articles/{a['id']}/markdown")
    assert md.status_code == 200 and "text/markdown" in md.headers["content-type"]


def test_blocked_article_cannot_be_approved(client):
    arts = client.get("/api/v1/articles").json()
    blocked = next(a for a in arts if a["compliance_status"] == "BLOCK")
    r = client.post(f"/api/v1/articles/{blocked['id']}/approve", json={"reviewer": "editor", "note": "please"})
    assert r.status_code == 409


def test_review_article_human_approval_and_revalidation(client):
    arts = client.get("/api/v1/articles").json()
    review = next(a for a in arts if a["compliance_status"] == "REVIEW")
    r = client.post(f"/api/v1/articles/{review['id']}/approve", json={"reviewer": "Legal Reviewer", "note": "checked sources"})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    v = client.post(f"/api/v1/articles/{review['id']}/validate").json()
    assert v["status"] == "REVIEW"
    assert client.get(f"/api/v1/articles/{review['id']}").json()["article"]["status"] == "APPROVED"


def test_ledger_csv_export(client):
    r = client.get("/api/v1/ledger/export")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert len([x for x in rows if x["entry_type"] == "ARTICLE_CREATED"]) >= 6
    assert {"run_id", "article_id", "target_keyword", "compliance_status", "evidence_sources"} <= set(rows[0])


def test_compliance_sandbox_blocks_bad_text(client):
    r = client.post("/api/v1/compliance/check", json={"markdown": "Earn guaranteed profits with zero risk! Sign up now.", "language": "en"})
    assert r.json()["status"] == "BLOCK"


def test_run_guards(client):
    assert client.post("/api/v1/demo/run-day/2").status_code == 409  # already completed
    assert client.post("/api/v1/demo/run-day/99").status_code == 404
    assert client.get("/api/v1/articles/00000000-0000-0000-0000-000000000000").status_code == 404


def test_runs_and_events(client):
    runs = client.get("/api/v1/runs", params={"top_level": True}).json()
    assert runs
    tree = client.get(f"/api/v1/runs/{runs[-1]['id']}/steps-tree").json()
    assert tree["steps"] and tree["children"]
    assert client.get(f"/api/v1/runs/{runs[-1]['id']}/events").json()


def test_settings_patch_is_validated(client):
    assert client.patch("/api/v1/settings", json={"india_authorization_status": "MAYBE"}).status_code == 422
