"""Seed the default demo tenant, project, tracked entities and simulated site inventory."""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.domain.embedding import get_embedder
from packages.domain.language import analyze_query
from packages.persistence.models import Article, ArticleVersion, Entity, Project, Tenant
from packages.providers.fixtures import inventory_fixture, project_fixture


def article_tokens(keyword: str, title: str) -> list[str]:
    a, b = analyze_query(keyword), analyze_query(title)
    seen: set[str] = set()
    return [t for t in a.concept_tokens + b.concept_tokens if not (t in seen or seen.add(t))]


def seed(session: Session) -> Project:
    fx = project_fixture()
    tenant = session.scalar(select(Tenant).where(Tenant.slug == fx["tenant"]["slug"]))
    if tenant is None:
        tenant = Tenant(name=fx["tenant"]["name"], slug=fx["tenant"]["slug"])
        session.add(tenant)
        session.flush()
    project = session.scalar(select(Project).where(Project.tenant_id == tenant.id, Project.slug == fx["project"]["slug"]))
    if project is None:
        p = fx["project"]
        project = Project(tenant_id=tenant.id, name=p["name"], slug=p["slug"], domain=p["domain"],
                          default_locale=p["default_locale"], settings=p["settings"])
        session.add(project)
        session.flush()
    existing = {e.key for e in session.scalars(select(Entity).where(Entity.project_id == project.id))}
    for e in fx["entities"]:
        if e["key"] not in existing:
            session.add(Entity(project_id=project.id, key=e["key"], name=e["name"], kind=e["kind"], aliases=e["aliases"]))
    seed_inventory(session, project)
    session.flush()
    return project


def seed_inventory(session: Session, project: Project) -> None:
    embedder = get_embedder()
    have = {a.slug for a in session.scalars(select(Article).where(Article.project_id == project.id))}
    for inv in inventory_fixture():
        if inv["slug"] in have:
            continue
        body = inv["body"]
        art = Article(
            project_id=project.id, origin="INVENTORY", slug=inv["slug"], title=inv["title"],
            target_keyword=inv["target_keyword"], language=inv["language"], locale="en-IN", theme=inv["theme"],
            intent=inv["intent"], intent_key=inv["intent_key"], entity_keys=[], content_type=inv["content_type"],
            content_class="EDUCATIONAL", status="PUBLISHED", compliance_status="N/A",
            publication_eligibility="ELIGIBLE_EDUCATIONAL", current_version=1,
            embedding=embedder.embed(article_tokens(inv["target_keyword"], inv["title"])),
        )
        art.versions.append(ArticleVersion(
            version=1, markdown=body, frontmatter={"title": inv["title"], "origin": "INVENTORY", "data_label": "SIMULATED INVENTORY"},
            seo={}, payload={}, brief={}, word_count=len(body.split()),
            content_hash=hashlib.sha256(body.encode()).hexdigest(), generator="pre-existing site page (simulated)",
            change_note="Simulated pre-existing inventory",
        ))
        session.add(art)


if __name__ == "__main__":
    from packages.persistence.db import session_scope

    with session_scope() as s:
        proj = seed(s)
        print(f"seeded project {proj.name} ({proj.id})")
