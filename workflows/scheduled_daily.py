"""ScheduledDailyWorkflow (Temporal): the target of the `atlas-daily` Temporal Schedule.

Every morning (06:00 IST by default) it creates today's LIVE run and executes DailyIntelligenceWorkflow on it.
Overlap policy SKIP on the schedule + the one-live-run-per-date guard make a double fire harmless.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from workflows.daily_intelligence import DailyIntelligenceWorkflow

RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), maximum_attempts=3)


@workflow.defn(name="ScheduledDailyWorkflow")
class ScheduledDailyWorkflow:
    @workflow.run
    async def run(self, trigger: str = "schedule") -> dict:
        created = await workflow.execute_activity("create_live_run", args=[trigger, False, "temporal"],
                                                  start_to_close_timeout=timedelta(minutes=1), retry_policy=RETRY)
        if not created.get("run_id"):
            return created
        result = await workflow.execute_child_workflow(DailyIntelligenceWorkflow.run, created["run_id"],
                                                       id=f"atlas-daily-live-{created['run_id']}")
        return {**created, "result": result}
