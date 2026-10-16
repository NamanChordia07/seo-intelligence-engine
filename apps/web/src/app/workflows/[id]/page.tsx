"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronRight, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Badge, Card, CardHeader, ErrorState, Loading, PageHeader, StatusBadge, Table, Td, Th, duration, fmtTime } from "@/components/ui";
import { TEMPORAL_UI_URL, api, type AuditEvent, type Run } from "@/lib/api";

type Step = { name: string; status: string; attempts: number; started_at: string; finished_at: string | null; detail: Record<string, any>; error: string | null };
type Node = Run & { steps: Step[]; children: Node[] };

function summarize(detail: Record<string, any>) {
  const keys = ["seeds_expanded", "observations", "new_candidates", "analysed", "scored", "selected_keywords", "status_counts", "capacity",
    "sources", "gaps", "title", "slug", "words", "generator", "status", "eligibility", "flagged", "reason"];
  return keys.filter((k) => detail[k] !== undefined && !(Array.isArray(detail[k]) && !detail[k].length))
    .map((k) => `${k}: ${typeof detail[k] === "object" ? JSON.stringify(detail[k]) : detail[k]}`);
}

function StepList({ steps }: { steps: Step[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <ol className="relative ml-3 border-l border-slate-200">
      {steps.map((s) => (
        <li key={s.name} className="mb-3 ml-5">
          <span className={`absolute -left-[7px] mt-1.5 h-3 w-3 rounded-full border-2 border-white ${s.status === "COMPLETED" ? "bg-emerald-500" : s.status === "FAILED" ? "bg-rose-500" : s.status === "SKIPPED" ? "bg-slate-300" : "bg-sky-500"}`} />
          <button onClick={() => setOpen(open === s.name ? null : s.name)} className="flex w-full flex-wrap items-center gap-2 text-left text-[13px]">
            <ChevronRight className={`h-3.5 w-3.5 text-slate-400 transition ${open === s.name ? "rotate-90" : ""}`} />
            <span className="font-medium text-slate-800">{s.name}</span><StatusBadge value={s.status} />
            {s.attempts > 1 && <Badge tone="amber">attempt {s.attempts}</Badge>}
            <span className="text-xs text-slate-400">{duration(s.started_at, s.finished_at)}</span>
          </button>
          <div className="ml-5 mt-0.5 space-y-0.5 text-xs text-slate-500">{summarize(s.detail).slice(0, 4).map((l) => <div key={l} className="truncate">{l}</div>)}</div>
          {s.error && <div className="ml-5 mt-1 rounded bg-rose-50 p-2 text-xs text-rose-800">{s.error}</div>}
          {open === s.name && <pre className="ml-5 mt-2 max-h-72 overflow-auto rounded bg-slate-950 p-3 text-[11px] text-slate-100">{JSON.stringify(s.detail, null, 2)}</pre>}
        </li>
      ))}
    </ol>
  );
}

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const tree = useQuery({
    queryKey: ["run-tree", id], queryFn: () => api<Node>(`/api/v1/runs/${id}/steps-tree`),
    refetchInterval: (q) => (["RUNNING", "QUEUED"].includes(q.state.data?.status ?? "") ? 1200 : false),
  });
  const events = useQuery({ queryKey: ["run-events", id, tree.data?.status], queryFn: () => api<AuditEvent[]>(`/api/v1/runs/${id}/events`) });
  if (tree.error) return <ErrorState error={tree.error} />;
  if (!tree.data) return <Loading />;
  const r = tree.data;
  return (
    <>
      <Link href="/workflows" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ArrowLeft className="h-4 w-4" /> Workflows</Link>
      <PageHeader title={`${r.kind.replaceAll("_", " ")}${r.sim_day ? ` · Day ${r.sim_day}` : ""}`}
        subtitle={<span>Run {r.id} · plan date {r.plan_date ?? "—"} · {fmtTime(r.started_at)} → {fmtTime(r.finished_at)} ({duration(r.started_at, r.finished_at)})</span>}
        actions={<>
          <StatusBadge value={r.status} /><Badge tone={r.orchestrator === "temporal" ? "indigo" : "slate"}>{r.orchestrator}</Badge>
          {r.temporal_workflow_id && <a className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:underline" target="_blank" rel="noopener noreferrer"
            href={`${TEMPORAL_UI_URL}/namespaces/default/workflows/${r.temporal_workflow_id}`}>Open in Temporal <ExternalLink className="h-3.5 w-3.5" /></a>}
        </>} />
      {r.error && <div className="mb-4"><ErrorState error={r.error} /></div>}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Pipeline steps" subtitle={r.stats?.orchestrator_reason} />
          <div className="p-5">
            <StepList steps={r.steps} />
            {r.children.map((c) => (
              <div key={c.id} className="mt-4 rounded-lg border border-slate-200 p-4">
                <div className="mb-3 flex flex-wrap items-center gap-2 text-[13px]">
                  <span className="font-semibold text-slate-800">{c.kind === "ARTICLE_GENERATION" ? "ArticleGenerationWorkflow" : c.kind.replaceAll("_", " ")}</span>
                  <StatusBadge value={c.status} />
                  <span className="text-xs text-slate-500">{c.stats?.keyword ?? (c.sim_day ? `Day ${c.sim_day}` : "")}</span>
                  {c.stats?.article_id && <Link className="ml-auto text-xs font-medium text-indigo-600 hover:underline" href={`/content/${c.stats.article_id}`}>article →</Link>}
                  {c.kind === "DAILY_INTELLIGENCE" && <Link className="ml-auto text-xs font-medium text-indigo-600 hover:underline" href={`/workflows/${c.id}`}>open →</Link>}
                </div>
                <StepList steps={c.steps} />
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <CardHeader title="Audit events" subtitle="Structured, persisted event log for this run and its child runs" />
          <Table>
            <thead><tr><Th>Time</Th><Th>Event</Th><Th>Message</Th></tr></thead>
            <tbody>{events.data?.map((e) => (
              <tr key={e.id}><Td className="whitespace-nowrap text-xs">{new Date(e.created_at).toLocaleTimeString("en-IN")}</Td>
                <Td><Badge tone={e.event_type.includes("BLOCK") || e.event_type.includes("FAIL") ? "red" : e.event_type.includes("REVIEW") ? "amber" : "slate"}>{e.event_type}</Badge></Td>
                <Td className="text-xs">{e.message}</Td></tr>
            ))}</tbody>
          </Table>
        </Card>
      </div>
    </>
  );
}
