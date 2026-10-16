"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText, Radar, ShieldCheck, Target } from "lucide-react";
import Link from "next/link";

import { DemoControls } from "@/components/demo-controls";
import {
  Badge, Card, CardHeader, Empty, ErrorState, LangBadge, Loading, PageHeader, ScoreBar, SourceBadge, Stat, StatusBadge,
  Table, Td, Th, duration, fmtTime,
} from "@/components/ui";
import { api, LANG_LABEL, type Dashboard } from "@/lib/api";

function Bars({ data, colors }: { data: Record<string, number>; colors?: Record<string, string> }) {
  const entries = Object.entries(data);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  if (!entries.length) return <div className="text-sm text-slate-400">No data yet</div>;
  return (
    <div className="space-y-2.5">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-center gap-3 text-[13px]">
          <div className="w-32 shrink-0 truncate text-slate-600">{LANG_LABEL[k] ?? k.replaceAll("_", " ")}</div>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
            <div className={`h-full rounded-full ${colors?.[k] ?? "bg-indigo-500"}`} style={{ width: `${(v / max) * 100}%` }} />
          </div>
          <div className="w-8 text-right font-semibold tabular-nums text-slate-800">{v}</div>
        </div>
      ))}
    </div>
  );
}

export default function Overview() {
  const { data, error, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/api/v1/dashboard"), refetchInterval: 8000 });

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="ATLAS discovers search demand around brokers popular with Indian traders, selects unique page opportunities each day, and drafts evidence-backed, compliance-gated content in English, Hindi and Hinglish."
      />
      <div className="mb-6"><DemoControls /></div>
      {error && <ErrorState error={error} />}
      {isLoading && <Loading />}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Queries discovered" value={data.counts.observations} icon={<Radar className="h-4 w-4" />}
              hint={<span className="flex flex-wrap gap-1">{Object.keys(data.observations_by_source_type).map((k) => <SourceBadge key={k} value={k} />)}</span>} />
            <Stat label="Opportunities scored" value={data.counts.opportunities} icon={<Target className="h-4 w-4" />}
              hint={`${data.opportunities_by_status.SELECTED ?? 0} selected · ${(data.opportunities_by_status.UPDATE_EXISTING ?? 0) + (data.opportunities_by_status.REJECTED ?? 0) + (data.opportunities_by_status.LOCALE_VARIANT ?? 0)} duplicates prevented`} />
            <Stat label="Pages generated" value={data.counts.articles_generated} icon={<FileText className="h-4 w-4" />}
              hint={`${data.counts.inventory_pages} pre-existing inventory pages · ${data.counts.redteam_articles} red-team draft`} />
            <Stat label="Compliance" icon={<ShieldCheck className="h-4 w-4" />}
              value={<span className="flex items-baseline gap-3 text-xl"><span className="text-emerald-600">{data.compliance.PASS}</span><span className="text-amber-600">{data.compliance.REVIEW}</span><span className="text-rose-600">{data.compliance.BLOCK}</span></span>}
              hint="PASS · REVIEW · BLOCK" />
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Top opportunity signals" subtitle="Why ATLAS chose today's pages (scores are explainable heuristics, not Google metrics)" action={<Link href="/opportunities" className="text-xs font-medium text-indigo-600 hover:underline">All opportunities →</Link>} />
              {data.top_opportunities.length === 0 ? <Empty title="No pages selected yet" hint="Run Day 1 to see the first selections." /> : (
                <ul className="divide-y divide-slate-100">
                  {data.top_opportunities.map((o) => (
                    <li key={o.id} className="flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <Link href={`/opportunities/${o.id}`} className="font-medium text-slate-900 hover:text-indigo-700">{o.keyword}</Link>
                        <div className="mt-1 flex flex-wrap gap-1.5"><LangBadge lang={o.language} /><Badge>Day {o.sim_day}</Badge>
                          {o.why.slice(0, 2).map((w) => <span key={w} className="text-xs text-slate-500">• {w}</span>)}</div>
                      </div>
                      <ScoreBar value={o.score} />
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <div className="space-y-6">
              <Card>
                <CardHeader title="Pages by language" />
                <div className="p-5"><Bars data={data.articles_by_language} colors={{ en: "bg-slate-500", hi: "bg-amber-500", "hi-Latn": "bg-indigo-500" }} /></div>
              </Card>
              <Card>
                <CardHeader title="Discovered queries by language" />
                <div className="p-5"><Bars data={data.observations_by_language} colors={{ en: "bg-slate-500", hi: "bg-amber-500", "hi-Latn": "bg-indigo-500" }} /></div>
              </Card>
            </div>
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Recent workflow runs" action={<Link href="/workflows" className="text-xs font-medium text-indigo-600 hover:underline">Workflow history →</Link>} />
              {data.recent_runs.length === 0 ? <Empty title="No runs yet" /> : (
                <Table>
                  <thead><tr><Th>Run</Th><Th>Status</Th><Th>Orchestrator</Th><Th>Pages</Th><Th>Started</Th><Th>Duration</Th></tr></thead>
                  <tbody>
                    {data.recent_runs.map((r) => (
                      <tr key={r.id} className="hover:bg-slate-50">
                        <Td><Link className="font-medium text-indigo-700 hover:underline" href={`/workflows/${r.id}`}>{r.kind.replaceAll("_", " ")}{r.sim_day ? ` · Day ${r.sim_day}` : ""}</Link></Td>
                        <Td><StatusBadge value={r.status} /></Td>
                        <Td><Badge tone={r.orchestrator === "temporal" ? "indigo" : "slate"}>{r.orchestrator}</Badge></Td>
                        <Td className="tabular-nums">{r.stats?.articles_generated ?? "—"}</Td>
                        <Td>{fmtTime(r.started_at ?? r.created_at)}</Td>
                        <Td>{duration(r.started_at, r.finished_at)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card>
            <Card>
              <CardHeader title="Opportunity decisions" subtitle="Cannibalization engine outcomes" />
              <div className="p-5"><Bars data={data.opportunities_by_status} colors={{ SELECTED: "bg-emerald-500", UPDATE_EXISTING: "bg-violet-500", LOCALE_VARIANT: "bg-sky-500", REJECTED: "bg-rose-500", DEFERRED: "bg-slate-400" }} /></div>
            </Card>
          </div>
          <p className="mt-6 text-xs text-slate-500">{data.data_label}</p>
        </>
      )}
    </>
  );
}
