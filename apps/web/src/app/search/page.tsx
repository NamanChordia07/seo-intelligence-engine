"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  Badge, Card, Empty, ErrorState, LangBadge, Loading, PageHeader, SimulatedNotice, SourceBadge, Table, Tabs, Td, Th,
} from "@/components/ui";
import { api } from "@/lib/api";

type Obs = {
  id: string; query: string; language: string; source: string; source_type: string; confidence: number;
  demand_proxy: number | null; trend_velocity: number | null; seed: string | null; entity_keys: string[]; is_news: boolean;
  sim_day: number | null; observed_at: string;
};
type Cand = {
  id: string; query: string; language: string; theme: string; intent: string; intent_key: string; entity_keys: string[];
  concept_tokens: string[]; demand_proxy: number | null; trend_velocity: number | null; source_types: string[];
  observation_count: number; first_seen_day: number | null; last_seen_day: number | null; is_news: boolean;
};
type Cluster = { id: string; intent_key: string; label: string; theme: string; intent: string; entity_keys: string[]; languages: string[]; candidate_count: number };

function Select({ value, onChange, options, label }: { value: string; onChange: (v: string) => void; options: [string, string][]; label: string }) {
  return (
    <label className="flex items-center gap-2 text-xs text-slate-500">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded-md border border-slate-200 bg-white px-2 py-1 text-sm text-slate-700">
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function trend(v: number | null) {
  if (v === null || v === undefined) return <span className="text-slate-400">n/a</span>;
  const cls = v >= 0.75 ? "text-emerald-600 font-semibold" : v > 0 ? "text-emerald-600" : "text-rose-600";
  return <span className={`tabular-nums ${cls}`}>{v >= 0 ? "+" : ""}{Math.round(v * 100)}%</span>;
}

function Observations() {
  const [lang, setLang] = useState("");
  const [day, setDay] = useState("");
  const [q, setQ] = useState("");
  const params = new URLSearchParams({ ...(lang && { language: lang }), ...(day && { day }), ...(q && { q }) });
  const { data, error, isLoading } = useQuery({ queryKey: ["observations", lang, day, q], queryFn: () => api<Obs[]>(`/api/v1/observations?${params}`) });
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-4 py-3">
        <Select label="Language" value={lang} onChange={setLang} options={[["", "All"], ["en", "English"], ["hi", "Hindi"], ["hi-Latn", "Hinglish"]]} />
        <Select label="Day" value={day} onChange={setDay} options={[["", "All"], ["1", "Day 1"], ["2", "Day 2"], ["3", "Day 3"]]} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter queries…" className="w-56 rounded-md border border-slate-200 px-2 py-1 text-sm" />
        <span className="ml-auto text-xs text-slate-500">{data?.length ?? 0} observations</span>
      </div>
      {error && <div className="p-4"><ErrorState error={error} /></div>}
      {isLoading ? <Loading /> : !data?.length ? <Empty title="No observations" hint="Run a simulated day from the Overview page." /> : (
        <Table>
          <thead><tr><Th>Query</Th><Th>Language</Th><Th>Broker / topic</Th><Th>Demand proxy</Th><Th>Trend</Th><Th>Source</Th><Th>Provenance</Th><Th>Day</Th></tr></thead>
          <tbody>
            {data.map((o) => (
              <tr key={o.id} className="hover:bg-slate-50">
                <Td className="font-medium text-slate-900">{o.query}{o.is_news && <Badge tone="red" className="ml-2">NEWS</Badge>}</Td>
                <Td><LangBadge lang={o.language} /></Td>
                <Td>{o.entity_keys.length ? o.entity_keys.join(", ") : <span className="text-slate-400">generic</span>}</Td>
                <Td className="tabular-nums">{o.demand_proxy ?? <span className="text-slate-400">n/a</span>}</Td>
                <Td>{trend(o.trend_velocity)}</Td>
                <Td className="text-xs">{o.source}{o.seed && <div className="text-slate-400">seed: {o.seed}</div>}</Td>
                <Td><SourceBadge value={o.source_type} /><div className="mt-0.5 text-[11px] text-slate-400">conf. {o.confidence}</div></Td>
                <Td>{o.sim_day ?? "live"}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

function Candidates() {
  const { data, error, isLoading } = useQuery({ queryKey: ["candidates"], queryFn: () => api<Cand[]>("/api/v1/candidates") });
  return (
    <Card>
      {error && <div className="p-4"><ErrorState error={error} /></div>}
      {isLoading ? <Loading /> : !data?.length ? <Empty title="No candidates yet" /> : (
        <Table>
          <thead><tr><Th>Normalized query</Th><Th>Lang</Th><Th>Theme / intent</Th><Th>Canonical intent key</Th><Th>Concept tokens</Th><Th>Seen</Th></tr></thead>
          <tbody>
            {data.map((c) => (
              <tr key={c.id} className="hover:bg-slate-50">
                <Td className="font-medium text-slate-900">{c.query}</Td>
                <Td><LangBadge lang={c.language} /></Td>
                <Td><Badge>{c.theme}</Badge> <span className="text-xs text-slate-500">{c.intent.replaceAll("_", " ")}</span></Td>
                <Td><code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{c.intent_key}</code></Td>
                <Td className="max-w-xs text-xs text-slate-500">{c.concept_tokens.join(" · ")}</Td>
                <Td className="text-xs">Day {c.first_seen_day}{c.last_seen_day !== c.first_seen_day && `→${c.last_seen_day}`} · {c.observation_count}×</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

function Clusters() {
  const { data, error, isLoading } = useQuery({ queryKey: ["clusters"], queryFn: () => api<Cluster[]>("/api/v1/clusters") });
  return (
    <Card>
      {error && <div className="p-4"><ErrorState error={error} /></div>}
      {isLoading ? <Loading /> : !data?.length ? <Empty title="No intent clusters yet" /> : (
        <Table>
          <thead><tr><Th>Intent key</Th><Th>Theme</Th><Th>Intent</Th><Th>Entities</Th><Th>Languages observed</Th><Th>Query variants</Th></tr></thead>
          <tbody>
            {data.map((c) => (
              <tr key={c.id} className="hover:bg-slate-50">
                <Td><code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{c.intent_key}</code></Td>
                <Td>{c.theme}</Td><Td className="text-xs">{c.intent.replaceAll("_", " ")}</Td>
                <Td>{c.entity_keys.join(", ") || "generic"}</Td>
                <Td><span className="flex gap-1">{c.languages.map((l) => <LangBadge key={l} lang={l} />)}</span></Td>
                <Td className="tabular-nums">{c.candidate_count}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

export default function SearchIntelligence() {
  return (
    <>
      <PageHeader title="Search Intelligence" subtitle="Seed expansion (brokers × themes × English/Hindi/Hinglish templates) → suggestion, trend and news providers → normalised candidates grouped into language-agnostic intent clusters." />
      <SimulatedNotice>Demand and trend values are SIMULATED relative indices (0-100 and % change) - never absolute search volumes. Live mode uses public autocomplete presence only (REAL_PUBLIC, no volume).</SimulatedNotice>
      <Tabs tabs={[
        { key: "obs", label: "Observations", content: <Observations /> },
        { key: "cand", label: "Keyword candidates", content: <Candidates /> },
        { key: "clusters", label: "Intent clusters", content: <Clusters /> },
      ]} />
    </>
  );
}
