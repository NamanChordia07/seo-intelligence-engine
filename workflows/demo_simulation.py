"""DemoSimulationWorkflow (Temporal): run simulated Day 1..N sequentially as child workflows."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from workflows.daily_intelligence import DailyIntelligenceWorkflow

RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), maximum_attempts=3)
T = timedelta(minutes=2)


@workflow.defn(name="DemoSimulationWorkflow")
class DemoSimulationWorkflow:
    @workflow.run
    async def run(self, parent_run_id: str, days: list[int]) -> dict:
        await workflow.execute_activity("start_run", parent_run_id, start_to_close_timeout=T, retry_policy=RETRY)
        results = {}
        failures: list[str] = []
        for day in days:
            day_run = await workflow.execute_activity("create_day_run", args=[parent_run_id, day],
                                                      start_to_close_timeout=T, retry_policy=RETRY)
            try:
                results[str(day)] = await workflow.execute_child_workflow(
                    DailyIntelligenceWorkflow.run, day_run, id=f"atlas-daily-{day_run}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"day {day}: {exc}")
                break  # later days depend on earlier inventory
        await workflow.execute_activity("finalize_run", args=[parent_run_id, failures], start_to_close_timeout=T,
                                        retry_policy=RETRY)
        return results
