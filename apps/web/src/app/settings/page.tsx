"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";

import { Button, Card, CardHeader, ErrorState, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { api, patch, post } from "@/lib/api";

export default function Settings() {
  const qc = useQueryClient();
  const { data, error, isLoading } = useQuery({ queryKey: ["settings"], queryFn: () => api<any>("/api/v1/settings") });
  const [msg, setMsg] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (v: string) => patch("/api/v1/settings", { india_authorization_status: v, actor: "demo-user" }),
    onSuccess: () => { setMsg("Saved. Re-run compliance on an article to see the gate change (BLOCK still can never be approved)."); qc.invalidateQueries(); },
    onError: (e: Error) => setMsg(e.message),
  });
  const probe = useMutation({ mutationFn: () => post<any>("/api/v1/discovery/live-probe"), onSuccess: (r) => setMsg(`Live probe stored ${r.observations ?? 0} REAL_PUBLIC observations${r.provider_failures?.length ? ` (provider failures: ${r.provider_failures.join("; ")})` : ""}.`), onError: (e: Error) => setMsg(e.message) });

  if (error) return <ErrorState error={error} />;
  if (isLoading || !data) return <Loading />;
  const s = data.project.settings;
  return (
    <>
      <PageHeader title="Settings" subtitle={`${data.project.name} · ${data.project.domain} (fictional) · default locale ${data.project.default_locale}`} />
      {msg && <div className="mb-4 rounded-lg bg-slate-100 px-3 py-2 text-[13px] text-slate-700" role="status">{msg}</div>}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="India authorization gate" subtitle="Has legal verified that the target platform may solicit Indian residents?" />
          <div className="space-y-3 p-5 text-[13px]">
            <div className="flex items-center gap-2">Current: <StatusBadge value={s.india_authorization_status} /></div>
            <div className="flex flex-wrap gap-2">
              {["UNKNOWN", "VERIFIED", "NOT_AUTHORIZED"].map((v) => (
                <Button key={v} variant={s.india_authorization_status === v ? "primary" : "secondary"} onClick={() => save.mutate(v)} loading={save.isPending && save.variables === v}>{v.replace("_", " ")}</Button>
              ))}
            </div>
            <p className="text-slate-500">UNKNOWN (default) → promotional content is BLOCKED_PENDING_AUTHORIZATION and never auto-approved. Educational content is unaffected. Every change is audit-logged.</p>
            <p className="text-slate-500">CTA policy: {s.cta_policy}</p>
          </div>
        </Card>
        <Card>
          <CardHeader title="Runtime" subtitle="Configured through environment variables (.env) - no secrets are stored in the database." />
          <dl className="grid grid-cols-[170px_1fr] gap-y-2 p-5 text-[13px]">
            {Object.entries(data.runtime).map(([k, v]) => <Fragment key={k}><dt className="text-slate-500">{k}</dt><dd className="text-slate-800">{String(v ?? "—")}</dd></Fragment>)}
            <dt className="text-slate-500">max_pages_per_day</dt><dd>{s.max_pages_per_day}</dd>
            <dt className="text-slate-500">languages</dt><dd>{s.languages.join(", ")}</dd>
          </dl>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title="Live discovery probe (optional, real public data)" subtitle="Queries a public autocomplete endpoint for a handful of seeds. Results are REAL_PUBLIC presence signals with no volume data; failures degrade gracefully." />
          <div className="p-5"><Button variant="secondary" onClick={() => probe.mutate()} loading={probe.isPending}>Run live probe</Button></div>
        </Card>
      </div>
    </>
  );
}
