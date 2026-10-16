"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import Link from "next/link";

import { DemoControls } from "@/components/demo-controls";
import { Badge, Card, CardHeader, Empty, ErrorState, Loading, PageHeader, StatusBadge, Table, Td, Th, duration, fmtTime } from "@/components/ui";
import { TEMPORAL_UI_URL, api, type Run } from "@/lib/api";

export default function Workflows() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["runs"], queryFn: () => api<Run[]>("/api/v1/runs?top_level=true"),
    refetchInterval: (q) => (q.state.data?.some((r) => ["RUNNING", "QUEUED"].includes(r.status)) ? 1500 : 10000),
  });
  return (
    <>
      <PageHeader title="Workflows" subtitle="Durable Temporal workflows (DailyIntelligenceWorkflow → ArticleGenerationWorkflow per page). If no Temporal worker is reachable the identical activity sequence runs inline, and that is recorded per run."
        actions={<a href={TEMPORAL_UI_URL} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Temporal UI <ExternalLink className="h-3.5 w-3.5" /></a>} />
      <div className="mb-6"><DemoControls /></div>
      <Card>
        <CardHeader title="Execution history" />
        {error && <div className="p-4"><ErrorState error={error} /></div>}
        {isLoading ? <Loading /> : !data?.length ? <Empty title="No workflow runs yet" /> : (
          <Table>
            <thead><tr><Th>Workflow</Th><Th>Status</Th><Th>Orchestrator</Th><Th>New pages</Th><Th>Opportunities</Th><Th>Started</Th><Th>Duration</Th><Th>Trigger</Th></tr></thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50" data-testid="run-row">
                  <Td><Link href={`/workflows/${r.id}`} className="font-medium text-indigo-700 hover:underline">{r.kind.replaceAll("_", " ")}{r.sim_day ? ` · Day ${r.sim_day}` : ""}</Link>
                    <div className="font-mono text-[10.5px] text-slate-400">{r.id.slice(0, 8)}{r.stats?.rerun ? " · re-run" : ""}</div></Td>
                  <Td><StatusBadge value={r.status} />{r.error && <div className="mt-1 max-w-xs truncate text-[11px] text-rose-600" title={r.error}>{r.error}</div>}</Td>
                  <Td><Badge tone={r.orchestrator === "temporal" ? "indigo" : "slate"}>{r.orchestrator}</Badge></Td>
                  <Td className="tabular-nums">{r.stats?.articles_generated ?? "—"}</Td>
                  <Td className="tabular-nums">{r.stats?.opportunities ?? "—"}</Td>
                  <Td>{fmtTime(r.started_at ?? r.created_at)}</Td>
                  <Td>{duration(r.started_at, r.finished_at)}</Td>
                  <Td className="text-xs">{r.trigger}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
