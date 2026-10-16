"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import {
  Badge, Card, Empty, ErrorState, LangBadge, Loading, PageHeader, ScoreBar, SimulatedNotice, StatusBadge, Table, Td, Th,
} from "@/components/ui";
import { api, type Opportunity } from "@/lib/api";

const STATUSES = ["", "SELECTED", "UPDATE_EXISTING", "LOCALE_VARIANT", "REJECTED", "DEFERRED"];

export default function Opportunities() {
  const [status, setStatus] = useState("");
  const [day, setDay] = useState("");
  const params = new URLSearchParams({ ...(status && { status }), ...(day && { day }) });
  const { data, error, isLoading } = useQuery({ queryKey: ["opportunities", status, day], queryFn: () => api<Opportunity[]>(`/api/v1/opportunities?${params}`) });

  return (
    <>
      <PageHeader title="Opportunities" subtitle="Every candidate is scored with an explainable breakdown, then checked against existing articles, today's plan and the database intent reservations before it can become a page." />
      <SimulatedNotice>Score components derived from SIMULATED signals are labelled per component. SERP weakness and competition are ATLAS heuristics - not Google, Ahrefs or Semrush metrics.</SimulatedNotice>
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
          {STATUSES.map((s) => (
            <button key={s || "all"} onClick={() => setStatus(s)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${status === s ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>
              {s ? s.replaceAll("_", " ") : "All"}
            </button>
          ))}
          <select value={day} onChange={(e) => setDay(e.target.value)} className="ml-auto rounded-md border border-slate-200 px-2 py-1 text-sm" aria-label="Day">
            <option value="">All days</option><option value="1">Day 1</option><option value="2">Day 2</option><option value="3">Day 3</option>
          </select>
        </div>
        {error && <div className="p-4"><ErrorState error={error} /></div>}
        {isLoading ? <Loading /> : !data?.length ? <Empty title="No opportunities" hint="Run a simulated day from the Overview page." /> : (
          <Table>
            <thead><tr><Th>Day · rank</Th><Th>Keyword</Th><Th>Score</Th><Th>Intent</Th><Th>Decision</Th><Th>Why / reason</Th></tr></thead>
            <tbody>
              {data.map((o) => (
                <tr key={o.id} className="hover:bg-slate-50" data-testid="opportunity-row">
                  <Td className="whitespace-nowrap text-xs text-slate-500">D{o.sim_day} · #{o.rank}</Td>
                  <Td>
                    <Link href={`/opportunities/${o.id}`} className="font-medium text-slate-900 hover:text-indigo-700">{o.keyword}</Link>
                    <div className="mt-1 flex flex-wrap gap-1"><LangBadge lang={o.language} /><Badge>{o.content_type.replaceAll("_", " ")}</Badge>
                      {o.content_class === "PROMOTIONAL" && <Badge tone="red">PROMOTIONAL</Badge>}</div>
                  </Td>
                  <Td><ScoreBar value={o.score} /></Td>
                  <Td><code className="text-xs text-slate-600">{o.intent_key}</code><div className="text-[11px] text-slate-400">{o.intent.replaceAll("_", " ")}</div></Td>
                  <Td><StatusBadge value={o.status} /><div className="mt-1 text-[11px] text-slate-400">{o.cannibalization?.decision?.replaceAll("_", " ")}</div></Td>
                  <Td className="max-w-md text-xs text-slate-600">
                    {o.status === "SELECTED" ? o.why.slice(0, 3).map((w) => <div key={w}>• {w}</div>) : o.status_reason}
                    {o.article_id && <div className="mt-1"><Link href={`/content/${o.article_id}`} className="font-medium text-indigo-600 hover:underline">Open article →</Link></div>}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
