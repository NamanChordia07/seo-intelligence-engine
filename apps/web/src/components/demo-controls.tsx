"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Play, PlayCircle, RotateCcw, Repeat } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { api, post, type DayStatus } from "@/lib/api";

import { Badge, Button, Card, CardHeader, ErrorState, StatusBadge } from "./ui";

export function useDemoStatus() {
  return useQuery({
    queryKey: ["demo-status"],
    queryFn: () => api<{ days: DayStatus[] }>("/api/v1/demo/status"),
    refetchInterval: (q) => (q.state.data?.days.some((d) => ["RUNNING", "QUEUED"].includes(d.status)) ? 1200 : 10000),
  });
}

export function DemoControls() {
  const qc = useQueryClient();
  const { data, error } = useDemoStatus();
  const [confirmReset, setConfirmReset] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const wasBusy = useRef(false);

  const busy = !!data?.days.some((d) => ["RUNNING", "QUEUED"].includes(d.status));
  useEffect(() => {
    if (wasBusy.current && !busy) qc.invalidateQueries();
    wasBusy.current = busy;
  }, [busy, qc]);

  const onError = (e: Error) => setMessage({ tone: "err", text: e.message });
  const runDay = useMutation({
    mutationFn: ({ day, force }: { day: number; force?: boolean }) =>
      post<{ run_id: string; orchestrator: string; reason: string }>(`/api/v1/demo/run-day/${day}${force ? "?force=true" : ""}`),
    onSuccess: (r, v) => {
      setMessage({ tone: "ok", text: `Day ${v.day}${v.force ? " re-run" : ""} started via ${r.orchestrator} orchestrator (${r.reason}).` });
      qc.invalidateQueries({ queryKey: ["demo-status"] });
    },
    onError,
  });
  const runAll = useMutation({
    mutationFn: () => post<{ run_id: string; orchestrator: string }>("/api/v1/demo/run-all"),
    onSuccess: (r) => { setMessage({ tone: "ok", text: `Full Day 1→3 simulation started via ${r.orchestrator}.` }); qc.invalidateQueries({ queryKey: ["demo-status"] }); },
    onError,
  });
  const reset = useMutation({
    mutationFn: () => post("/api/v1/demo/reset"),
    onSuccess: () => { setConfirmReset(false); setMessage({ tone: "ok", text: "Demo reset. Simulated inventory re-seeded." }); qc.invalidateQueries(); },
    onError,
  });

  const days = data?.days ?? [];
  const nextDay = days.find((d) => d.status === "NOT_RUN" || d.status === "FAILED")?.day;

  return (
    <Card>
      <CardHeader
        title={<span className="flex items-center gap-2"><CalendarDays className="h-4 w-4 text-indigo-500" />Simulated daily runs</span>}
        subtitle="Each day runs the full DailyIntelligenceWorkflow: discover → score → deduplicate → plan → research → write → validate → log."
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => runAll.mutate()} loading={runAll.isPending} disabled={busy || days.some((d) => d.status !== "NOT_RUN")} data-testid="run-all">
              <PlayCircle className="h-4 w-4" /> Run Day 1→3
            </Button>
            {confirmReset ? (
              <>
                <Button variant="danger" onClick={() => reset.mutate()} loading={reset.isPending} data-testid="confirm-reset">Confirm reset</Button>
                <Button variant="ghost" onClick={() => setConfirmReset(false)}>Cancel</Button>
              </>
            ) : (
              <Button variant="ghost" onClick={() => setConfirmReset(true)} disabled={busy} data-testid="reset"><RotateCcw className="h-4 w-4" /> Reset demo</Button>
            )}
          </div>
        }
      />
      {error && <div className="p-4"><ErrorState error={error} /></div>}
      <div className="grid gap-3 p-4 md:grid-cols-3">
        {days.map((d) => {
          const done = d.status === "COMPLETED" || d.status === "PARTIAL";
          return (
            <div key={d.day} className="flex flex-col rounded-lg border border-slate-200 p-4" data-testid={`day-card-${d.day}`}>
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-slate-900">Day {d.day} <span className="font-normal text-slate-500">· {d.date}</span></div>
                <StatusBadge value={d.status} />
              </div>
              <p className="mt-2 min-h-[40px] text-[12.5px] leading-relaxed text-slate-500">{d.narrative}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                <Badge tone="violet">{d.observations_fixture} simulated signals</Badge>
                {done && <Badge tone="green">{d.articles} new pages</Badge>}
                {done && d.redteam_articles > 0 && <Badge tone="red">{d.redteam_articles} red-team draft blocked</Badge>}
              </div>
              <div className="mt-4 flex gap-2">
                {!done ? (
                  <Button onClick={() => runDay.mutate({ day: d.day })} disabled={busy || d.day !== nextDay} loading={runDay.isPending && runDay.variables?.day === d.day} data-testid={`run-day-${d.day}`}>
                    <Play className="h-3.5 w-3.5" /> Run Day {d.day}
                  </Button>
                ) : (
                  <Button variant="secondary" onClick={() => runDay.mutate({ day: d.day, force: true })} disabled={busy} title="Re-run to show that duplicates are refused">
                    <Repeat className="h-3.5 w-3.5" /> Re-run (dup test)
                  </Button>
                )}
                {d.latest_run_id && <Link href={`/workflows/${d.latest_run_id}`} className="self-center text-xs font-medium text-indigo-600 hover:underline">View run →</Link>}
              </div>
            </div>
          );
        })}
      </div>
      {message && (
        <div className={`mx-4 mb-4 rounded-lg px-3 py-2 text-[13px] ${message.tone === "ok" ? "bg-emerald-50 text-emerald-800" : "bg-rose-50 text-rose-800"}`} role="status">
          {message.text}
        </div>
      )}
    </Card>
  );
}
