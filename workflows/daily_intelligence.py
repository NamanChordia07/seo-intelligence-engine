"""DailyIntelligenceWorkflow (Temporal).

discover -> normalize -> analyze SERPs -> score + deduplicate + reserve intents + plan
  -> ArticleGenerationWorkflow per selected opportunity (research -> generate -> validate -> store/log)
  -> optional red-team compliance probe -> finalize

All business state lives in PostgreSQL; every activity is idempotent per run, so
Temporal retries / replays never duplicate observations, opportunities or articles.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from workflows.article_generation import ArticleGenerationWorkflow

RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_attempts=3)
T = timedelta(minutes=5)


@workflow.defn(name="DailyIntelligenceWorkflow")
class DailyIntelligenceWorkflow:
    def __init__(self) -> None:
        self.stage = "queued"

    @workflow.query
    def current_stage(self) -> str:
        return self.stage

    @workflow.run
    async def run(self, run_id: str) -> dict:
        try:
            self.stage = "start"
            started = await workflow.execute_activity("start_run", run_id, start_to_close_timeout=T, retry_policy=RETRY)
            for stage in ("discover", "normalize", "analyze_serps"):
                self.stage = stage
                await workflow.execute_activity(stage, run_id, start_to_close_timeout=T, retry_policy=RETRY)
            self.stage = "score_and_select"
            plan = await workflow.execute_activity("score_and_select", run_id, start_to_close_timeout=T, retry_policy=RETRY)
            failures: list[str] = []
            for opp_id in plan["selected"]:
                self.stage = f"article:{opp_id}"
                try:
                    await workflow.execute_child_workflow(
                        ArticleGenerationWorkflow.run, args=[run_id, opp_id], id=f"atlas-article-{run_id}-{opp_id}",
                    )
                except ChildWorkflowError as exc:
                    failures.append(f"article {opp_id}: {exc.cause or exc}")
            if started.get("redteam"):
                self.stage = "redteam"
                red = await workflow.execute_activity("generate_redteam", run_id, start_to_close_timeout=T, retry_policy=RETRY)
                await workflow.execute_activity("validate_article", args=[run_id, red["article_id"]],
                                                start_to_close_timeout=T, retry_policy=RETRY)
            self.stage = "finalize"
            return await workflow.execute_activity("finalize_run", args=[run_id, failures], start_to_close_timeout=T,
                                                   retry_policy=RETRY)
        except Exception as exc:
            await workflow.execute_activity("fail_run", args=[run_id, str(exc)[:1000]], start_to_close_timeout=T,
                                            retry_policy=RETRY)
            raise
