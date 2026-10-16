"""Client-side management of the `atlas-daily` Temporal Schedule (cron in India time, overlap SKIP)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from packages.config import get_settings
from workflows.engine import temporal_client

SCHEDULE_ID = "atlas-daily"


async def ensure_schedule(paused: bool = False) -> dict[str, Any]:
    """Create the schedule if missing (idempotent); an existing schedule keeps its paused state."""
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleAlreadyRunningError,
        ScheduleOverlapPolicy,
        SchedulePolicy,
        ScheduleSpec,
        ScheduleState,
    )

    s = get_settings()
    client = await temporal_client()
    try:
        await client.create_schedule(SCHEDULE_ID, Schedule(
            action=ScheduleActionStartWorkflow("ScheduledDailyWorkflow", "schedule", id="atlas-daily-live",
                                               task_queue=s.temporal_task_queue, execution_timeout=timedelta(hours=2)),
            spec=ScheduleSpec(cron_expressions=[s.schedule_cron], time_zone_name=s.schedule_timezone),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=timedelta(hours=6)),
            state=ScheduleState(paused=paused, note="ATLAS daily live run"),
        ))
    except ScheduleAlreadyRunningError:
        pass
    return await describe_schedule()


async def describe_schedule() -> dict[str, Any]:
    from temporalio.service import RPCError

    s = get_settings()
    out: dict[str, Any] = {"id": SCHEDULE_ID, "cron": s.schedule_cron, "timezone": s.schedule_timezone,
                           "temporal_ui": f"{s.temporal_ui_url}/namespaces/{s.temporal_namespace}/schedules/{SCHEDULE_ID}"}
    try:
        client = await temporal_client()
        desc = await client.get_schedule_handle(SCHEDULE_ID).describe()
    except RPCError:
        return {**out, "exists": False, "available": True}
    except Exception as exc:  # noqa: BLE001 - Temporal down: report it, never crash the API
        return {**out, "exists": False, "available": False, "error": type(exc).__name__}
    info = desc.info
    return {
        **out, "exists": True, "available": True, "paused": desc.schedule.state.paused,
        "next_runs": [t.isoformat() for t in info.next_action_times[:3]],
        "recent": [{"scheduled": a.scheduled_at.isoformat(), "started": a.started_at.isoformat()}
                   for a in info.recent_actions[-5:]],
        "num_actions": info.num_actions,
    }


async def set_paused(paused: bool) -> dict[str, Any]:
    client = await temporal_client()
    handle = client.get_schedule_handle(SCHEDULE_ID)
    if paused:
        await handle.pause(note="paused from ATLAS")
    else:
        await handle.unpause(note="resumed from ATLAS")
    return await describe_schedule()
