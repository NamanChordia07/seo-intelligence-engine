"""End-to-end Day 1-3 simulation against PostgreSQL (inline orchestrator)."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from packages.persistence.db import session_scope
from packages.persistence.models import (
    Article,
    ArticleVersion,
    ComplianceDecision,
    EvidenceClaim,
    IntentReservation,
    InternalLink,
    LedgerEntry,
    OpportunityRow,
    WorkflowRun,
    WorkflowStep,
)


def generated(s, pid, include_test=False):
    q = select(Article).where(Article.project_id == pid, Article.origin == "GENERATED")
    if not include_test:
        q = q.where(Article.is_test_fixture.is_(False))
    return list(s.scalars(q))


def test_two_or_more_unique_pages_per_day(demo_world):
    with session_scope() as s:
        arts = generated(s, demo_world["project_id"])
        assert len(arts) >= 6
        for day in (1, 2, 3):
            assert len([a for a in arts if a.sim_day == day]) >= 2
        assert len({a.intent_key for a in arts}) == len(arts), "duplicate intents scheduled"
        assert len({a.slug for a in arts}) == len(arts)


def test_multilingual_output(demo_world):
    with session_scope() as s:
        langs = {a.language for a in generated(s, demo_world["project_id"])}
    assert {"en", "hi", "hi-Latn"} <= langs


def test_runs_completed_with_steps(demo_world):
    with session_scope() as s:
        for day in (1, 2, 3):
            run = s.get(WorkflowRun, __import__("uuid").UUID(demo_world["runs"][day]))
            assert run.status == "COMPLETED", run.error
            steps = {st.name for st in s.scalars(select(WorkflowStep).where(WorkflowStep.run_id == run.id))}
            assert {"discover", "normalize", "analyze_serps", "score_and_select"} <= steps


def test_cannibalization_prevented_and_recorded(demo_world):
    with session_scope() as s:
        opps = list(s.scalars(select(OpportunityRow).where(OpportunityRow.project_id == demo_world["project_id"])))
        statuses = {o.status for o in opps}
        assert {"UPDATE_EXISTING", "LOCALE_VARIANT", "REJECTED", "SELECTED"} <= statuses
        rejected_xm = [o for o in opps if o.keyword == "xm vs exness" and o.sim_day == 3]
        assert rejected_xm and rejected_xm[0].status == "UPDATE_EXISTING"
        # every selected opportunity owns exactly one DB reservation
        res = {r.intent_key for r in s.scalars(select(IntentReservation).where(IntentReservation.project_id == demo_world["project_id"]))}
        assert {o.intent_key for o in opps if o.status == "SELECTED"} == res


def test_reservation_unique_constraint_enforced(demo_world):
    with session_scope() as s:
        key = s.scalars(select(IntentReservation.intent_key)).first()
    with pytest.raises(IntegrityError), session_scope() as s:
        s.add(IntentReservation(project_id=demo_world["project_id"], intent_key=key))
        s.flush()


def test_duplicate_slug_rejected_by_database(demo_world):
    with session_scope() as s:
        a = generated(s, demo_world["project_id"])[0]
        slug, pid = a.slug, a.project_id
    with pytest.raises(IntegrityError), session_scope() as s:
        s.add(Article(project_id=pid, slug=slug, title="dup", target_keyword="dup", language="en", locale="en-IN",
                      theme="fees", intent="informational", intent_key="fees:dup", content_type="guide",
                      content_class="EDUCATIONAL"))
        s.flush()


def test_internal_links_point_to_earlier_articles(demo_world):
    with session_scope() as s:
        arts = {a.id: a for a in s.scalars(select(Article).where(Article.project_id == demo_world["project_id"]))}
        inserted = list(s.scalars(select(InternalLink).where(InternalLink.direction == "INSERTED")))
        day2_to_day1 = [link for link in inserted if arts[link.source_article_id].sim_day == 2 and arts[link.target_article_id].sim_day == 1]
        day3_to_earlier = [link for link in inserted if arts[link.source_article_id].sim_day == 3
                           and (arts[link.target_article_id].sim_day or 0) in (1, 2)]
        assert day2_to_day1 and day3_to_earlier
        for link in inserted:  # never link forward in time / to blocked drafts
            tgt = arts[link.target_article_id]
            assert tgt.status != "BLOCKED"


def test_compliance_outcomes(demo_world):
    with session_scope() as s:
        arts = generated(s, demo_world["project_id"], include_test=True)
        red = [a for a in arts if a.is_test_fixture]
        assert len(red) == 1 and red[0].compliance_status == "BLOCK" and red[0].status == "BLOCKED"
        real = [a for a in arts if not a.is_test_fixture]
        assert all(a.compliance_status in ("PASS", "REVIEW") for a in real)
        assert any(a.compliance_status == "PASS" for a in real)
        for a in arts:
            d = s.scalar(select(ComplianceDecision).where(ComplianceDecision.article_id == a.id))
            assert d is not None and len(d.rule_results) >= 15


def test_evidence_and_versions_persisted(demo_world):
    with session_scope() as s:
        for a in generated(s, demo_world["project_id"]):
            claims = list(s.scalars(select(EvidenceClaim).where(EvidenceClaim.article_id == a.id)))
            assert len({c.source_id for c in claims}) >= 2
            v = s.scalar(select(ArticleVersion).where(ArticleVersion.article_id == a.id))
            assert v.version == 1 and v.markdown.startswith("---") and "## " in v.markdown
            assert v.seo["json_ld"]["faq"]["@type"] == "FAQPage"


def test_ledger_contains_every_article(demo_world):
    with session_scope() as s:
        ids = {a.id for a in generated(s, demo_world["project_id"], include_test=True)}
        ledger = list(s.scalars(select(LedgerEntry).where(LedgerEntry.project_id == demo_world["project_id"])))
        created = {e.article_id for e in ledger if e.entry_type in ("ARTICLE_CREATED", "REDTEAM_BLOCKED")}
        assert ids <= created
        assert any(e.entry_type == "UPDATE_EXISTING_RECOMMENDED" for e in ledger)
        row = next(e for e in ledger if e.entry_type == "ARTICLE_CREATED")
        assert row.run_id and row.target_slug and row.compliance_status and row.evidence_sources and row.article_version == 1


def test_forced_rerun_creates_no_duplicates(demo_world):
    from packages.providers.fixtures import day_config
    from workflows.engine import run_daily_inline

    with session_scope() as s:
        before = len(generated(s, demo_world["project_id"]))
        r = WorkflowRun(project_id=demo_world["project_id"], kind="DAILY_INTELLIGENCE", sim_day=1,
                        plan_date=day_config(1)["date"], status="QUEUED", orchestrator="inline")
        s.add(r)
        s.flush()
        rid = str(r.id)
    stats = run_daily_inline(rid)
    assert stats["articles_generated"] == 0 and not stats["failures"]
    with session_scope() as s:
        assert len(generated(s, demo_world["project_id"])) == before
