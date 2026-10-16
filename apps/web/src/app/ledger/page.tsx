"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge, Card, Empty, ErrorState, LangBadge, Loading, PageHeader, StatusBadge, Table, Tabs, Td, Th, fmtTime } from "@/components/ui";
import { API_URL, api, type AuditEvent } from "@/lib/api";

type Row = Record<string, any>;

const TYPE_TONE: Record<string, string> = {
  ARTICLE_CREATED: "green", HUMAN_APPROVED: "green", REDTEAM_BLOCKED: "red", OPPORTUNITY_REJECTED: "red",
  UPDATE_EXISTING_RECOMMENDED: "violet", LOCALE_VARIANT_DEFERRED: "blue", COMPLIANCE_REVALIDATED: "amber",
};

function Ledger() {
  const { data, error, isLoading } = useQuery({ queryKey: ["ledger"], queryFn: () => api<Row[]>("/api/v1/ledger") });
  const [type, setType] = useState("");
  const rows = (data ?? []).filter((r) => !type || r.entry_type === type);
  const types = Array.from(new Set((data ?? []).map((r) => r.entry_type)));
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
        <button onClick={() => setType("")} className={`rounded-md px-2.5 py-1 text-xs font-medium ${!type ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-600"}`}>All ({data?.length ?? 0})</button>
        {types.map((t) => <button key={t} onClick={() => setType(t)} className={`rounded-md px-2.5 py-1 text-xs font-medium ${type === t ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-600"}`}>{t.replaceAll("_", " ")}</button>)}
      </div>
      {error && <div className="p-4"><ErrorState error={error} /></div>}
      {isLoading ? <Loading /> : !rows.length ? <Empty title="Ledger is empty" hint="Run a simulated day to start the running sheet." /> : (
        <Table>
          <thead><tr><Th>Plan date</Th><Th>Entry</Th><Th>Target keyword</Th><Th>Lang</Th><Th>Intent</Th><Th>Score</Th><Th>Slug</Th><Th>Content</Th><Th>Compliance</Th><Th>Workflow</Th><Th>Sources</Th><Th>v</Th><Th>Run</Th><Th>Logged</Th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="hover:bg-slate-50" data-testid="ledger-row">
                <Td className="whitespace-nowrap text-xs">{r.plan_date ?? "—"}{r.sim_day && <div className="text-slate-400">Day {r.sim_day}</div>}</Td>
                <Td><Badge tone={TYPE_TONE[r.entry_type] ?? "slate"}>{r.entry_type.replaceAll("_", " ")}</Badge></Td>
                <Td className="max-w-[220px] font-medium text-slate-900">{r.article_id ? <Link className="hover:text-indigo-700" href={`/content/${r.article_id}`}>{r.target_keyword}</Link> : r.target_keyword}
                  {r.note && <div className="mt-0.5 line-clamp-2 text-[11px] font-normal text-slate-500" title={r.note}>{r.note}</div>}</Td>
                <Td><LangBadge lang={r.language} /></Td>
                <Td className="text-xs">{r.intent?.replaceAll("_", " ")}<div className="font-mono text-[10.5px] text-slate-400">{r.intent_key}</div></Td>
                <Td className="tabular-nums">{r.opportunity_score?.toFixed?.(1) ?? "—"}</Td>
                <Td className="max-w-[160px] truncate font-mono text-[11px]" >{r.target_slug}</Td>
                <Td><StatusBadge value={r.content_status} /></Td>
                <Td><StatusBadge value={r.compliance_status} /></Td>
                <Td><StatusBadge value={r.workflow_status} /></Td>
                <Td className="tabular-nums" >{r.evidence_sources?.length ?? 0}</Td>
                <Td>{r.article_version ?? "—"}</Td>
                <Td className="font-mono text-[10.5px]">{r.run_id ? <Link className="text-indigo-600 hover:underline" href={`/workflows/${r.run_id}`}>{r.run_id.slice(0, 8)}</Link> : "—"}</Td>
                <Td className="whitespace-nowrap text-xs">{fmtTime(r.created_at)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

function Audit() {
  const [q, setQ] = useState("");
  const { data, error, isLoading } = useQuery({ queryKey: ["audit", q], queryFn: () => api<AuditEvent[]>(`/api/v1/audit-events?limit=500${q ? `&q=${encodeURIComponent(q)}` : ""}`) });
  return (
    <Card>
      <div className="border-b border-slate-100 px-4 py-3"><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search events…" className="w-64 rounded-md border border-slate-200 px-2 py-1 text-sm" /></div>
      {error && <div className="p-4"><ErrorState error={error} /></div>}
      {isLoading ? <Loading /> : (
        <Table>
          <thead><tr><Th>Time</Th><Th>Event</Th><Th>Actor</Th><Th>Message</Th><Th>Links</Th></tr></thead>
          <tbody>{data?.map((e) => (
            <tr key={e.id}>
              <Td className="whitespace-nowrap text-xs">{fmtTime(e.created_at)}</Td>
              <Td><Badge tone={e.event_type.includes("BLOCK") || e.event_type.includes("FAIL") ? "red" : e.event_type.includes("REVIEW") ? "amber" : e.event_type.includes("PASS") || e.event_type.includes("APPROV") ? "green" : "slate"}>{e.event_type}</Badge></Td>
              <Td className="text-xs">{e.actor}</Td>
              <Td className="text-xs">{e.message}</Td>
              <Td className="whitespace-nowrap text-xs">{e.run_id && <Link className="mr-2 text-indigo-600 hover:underline" href={`/workflows/${e.run_id}`}>run</Link>}{e.article_id && <Link className="text-indigo-600 hover:underline" href={`/content/${e.article_id}`}>article</Link>}</Td>
            </tr>
          ))}</tbody>
        </Table>
      )}
    </Card>
  );
}

export default function LedgerPage() {
  return (
    <>
      <PageHeader title="Audit / Ledger" subtitle="The running sheet: an append-only PostgreSQL ledger of every page created, every duplicate refused and every compliance/approval decision - exportable as CSV."
        actions={<a href={`${API_URL}/api/v1/ledger/export`} className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-700" data-testid="csv-export"><Download className="h-4 w-4" /> Download CSV</a>} />
      <Tabs tabs={[{ key: "ledger", label: "Content ledger", content: <Ledger /> }, { key: "audit", label: "Audit events", content: <Audit /> }]} />
    </>
  );
}
