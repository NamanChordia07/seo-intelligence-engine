"""ArticleGenerationWorkflow (Temporal child workflow): brief -> research -> draft -> validate.

Activities are referenced by name so this module stays free of non-deterministic
imports (database, HTTP) inside the Temporal workflow sandbox.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_attempts=3)
SHORT = timedelta(minutes=2)
LONG = timedelta(minutes=10)


@workflow.defn(name="ArticleGenerationWorkflow")
class ArticleGenerationWorkflow:
    @workflow.run
    async def run(self, parent_run_id: str, opportunity_id: str) -> dict:
        child_run = await workflow.execute_activity("create_article_run", args=[parent_run_id, opportunity_id],
                                                    start_to_close_timeout=SHORT, retry_policy=RETRY)
        try:
            await workflow.execute_activity("plan_brief", args=[child_run, opportunity_id],
                                            start_to_close_timeout=SHORT, retry_policy=RETRY)
            await workflow.execute_activity("research_evidence", args=[child_run, opportunity_id],
                                            start_to_close_timeout=LONG, retry_policy=RETRY)
            gen = await workflow.execute_activity("generate_article", args=[child_run, opportunity_id],
                                                  start_to_close_timeout=LONG, retry_policy=RETRY)
            result = await workflow.execute_activity("validate_article", args=[child_run, gen["article_id"]],
                                                     start_to_close_timeout=SHORT, retry_policy=RETRY)
            await workflow.execute_activity("complete_article_run", args=[child_run, True, ""],
                                            start_to_close_timeout=SHORT, retry_policy=RETRY)
            return {"article_id": gen["article_id"], "compliance": result.get("status"), "child_run_id": child_run}
        except Exception as exc:  # noqa: BLE001 - record failure, let parent continue with other pages
            await workflow.execute_activity("complete_article_run", args=[child_run, False, str(exc)[:500]],
                                            start_to_close_timeout=SHORT, retry_policy=RETRY)
            raise
