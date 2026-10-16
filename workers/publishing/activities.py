"""Publishing worker: rebuild the static site from the database after every run (or on demand).

Two builds from the same inputs:
* outputs/site          - production build (root-relative links), ready to upload to any static host / CDN
* .data/site-preview    - same pages with links under /site so the API can serve a live preview
Builds go to a temp directory and are swapped in, so a reader never sees a half-written site.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from temporalio import activity

from packages.config import ROOT_DIR, get_settings
from packages.persistence.db import session_scope
from packages.persistence.models import Article, Project
from packages.persistence.repositories import audit, get_default_project
from packages.publishing.site import PageInput, ProjectInput, build_site

PREVIEW_DIR = ROOT_DIR / ".data" / "site-preview"
PREVIEW_BASE = "/site"


def _inputs(s, project: Project) -> tuple[list[PageInput], ProjectInput]:
    pages = []
    for a in s.scalars(select(Article).where(Article.project_id == project.id).order_by(Article.created_at)):
        v = a.versions[-1] if a.versions else None
        if v is None:
            continue
        fm = v.frontmatter or {}
        pages.append(PageInput(
            article_id=str(a.id), slug=a.slug, language=a.language, title=a.title,
            meta_description=(v.seo or {}).get("meta_description") or fm.get("description") or a.title,
            markdown=v.markdown, status=a.status, compliance_status=a.compliance_status,
            eligibility=a.publication_eligibility, content_class=a.content_class, origin=a.origin,
            intent_key=a.intent_key, updated=(a.updated_at or a.created_at).date().isoformat(), seo=v.seo or {},
            is_test_fixture=a.is_test_fixture,
        ))
    st = project.settings or {}
    return pages, ProjectInput(
        domain=project.domain, site_name=st.get("target_platform_name", project.name),
        authorization=st.get("india_authorization_status", "UNKNOWN"),
        platform_name=st.get("target_platform_name", project.name), platform_url=st.get("target_platform_url"),
    )


def _write(files: dict[str, bytes], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".build-", dir=target.parent))
    for rel, data in files.items():
        out = tmp / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    old = target.with_name(target.name + ".old")
    if target.exists():
        shutil.rmtree(old, ignore_errors=True)
        target.rename(old)
    tmp.rename(target)
    shutil.rmtree(old, ignore_errors=True)


def publish_site(run_id: str | None = None, actor: str = "system") -> dict[str, Any]:
    with session_scope() as s:
        project = get_default_project(s)
        pages, proj = _inputs(s, project)
        files, report = build_site(pages, proj)
        preview_files, _ = build_site(pages, proj, base=PREVIEW_BASE)
        site_dir = get_settings().site_path
        files["site-report.json"] = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        _write(files, site_dir)
        _write(preview_files, PREVIEW_DIR)
        c, perf = report["counts"], report["performance"]
        audit(s, project.id, "SITE_BUILT",
              f"Static site built: {c['PUBLISH']} indexable, {c['PREVIEW']} preview (noindex), {c['EXCLUDE']} excluded; "
              f"largest page {perf['max_gzip_bytes'] / 1000:.1f} KB gz, est. {perf['max_est_load_ms']} ms on Slow 4G",
              run_id=run_id, actor=actor, payload={"counts": c, "performance": perf, "output": str(site_dir)})
        return {**report, "output_dir": str(site_dir), "preview_url": f"{PREVIEW_BASE}/"}


def latest_report() -> dict[str, Any] | None:
    path = get_settings().site_path / "site-report.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@activity.defn(name="build_site")
def build_site_activity(run_id: str) -> dict[str, Any]:
    report = publish_site(run_id)
    return {"counts": report["counts"], "performance": report["performance"]}
