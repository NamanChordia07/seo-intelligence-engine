"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { RuleChecklist } from "@/components/rule-checklist";
import { Badge, Button, Card, CardHeader, Empty, ErrorState, LangBadge, Loading, PageHeader, StatusBadge, Table, Tabs, Td, Th, fmtTime } from "@/components/ui";
import { api, post, type Decision, type RuleResult } from "@/lib/api";

type Rule = { rule_id: string; name: string; category: string; severity: string; description: string };

const SAMPLE_BAD = `# Exness Bonus - Earn Guaranteed Profits!

Earn guaranteed profits with zero risk. Exness is the best broker in India and it is RBI approved.
I made ₹50,000 in my first week. Open an account now and claim your bonus!`;

function Sandbox() {
  const [md, setMd] = useState(SAMPLE_BAD);
  const [language, setLanguage] = useState("en");
  const [cls, setCls] = useState("EDUCATIONAL");
  const check = useMutation({ mutationFn: () => post<{ status: string; publication_eligibility: string; rule_results: RuleResult[] }>("/api/v1/compliance/check", { markdown: md, language, content_class: cls }) });
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card className="p-4">
        <div className="mb-2 text-sm font-semibold text-slate-800">Paste any draft (Markdown) — nothing is stored</div>
        <textarea value={md} onChange={(e) => setMd(e.target.value)} rows={14} className="w-full rounded-lg border border-slate-200 p-3 font-mono text-[12.5px]" data-testid="sandbox-input" />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <select value={language} onChange={(e) => setLanguage(e.target.value)} className="rounded-md border border-slate-200 px-2 py-1 text-sm" aria-label="Language">
            <option value="en">English</option><option value="hi">Hindi</option><option value="hi-Latn">Hinglish</option>
          </select>
          <select value={cls} onChange={(e) => setCls(e.target.value)} className="rounded-md border border-slate-200 px-2 py-1 text-sm" aria-label="Content class">
            <option value="EDUCATIONAL">Educational</option><option value="PROMOTIONAL">Promotional</option>
          </select>
          <Button onClick={() => check.mutate()} loading={check.isPending} data-testid="sandbox-run">Run policy engine</Button>
          <button className="text-xs text-slate-500 underline" onClick={() => setMd(SAMPLE_BAD)}>load unsafe sample</button>
        </div>
      </Card>
      <div>
        {check.error && <ErrorState error={check.error} />}
        {check.data ? (
          <>
            <div className="mb-3 flex items-center gap-2" data-testid="sandbox-result"><StatusBadge value={check.data.status} /><StatusBadge value={check.data.publication_eligibility} /></div>
            <RuleChecklist results={check.data.rule_results} />
          </>
        ) : <Card><Empty title="Run the policy engine to see rule-by-rule results" /></Card>}
      </div>
    </div>
  );
}

export default function Compliance() {
  const rules = useQuery({ queryKey: ["rules"], queryFn: () => api<Rule[]>("/api/v1/compliance/rules") });
  const decisions = useQuery({ queryKey: ["decisions"], queryFn: () => api<Decision[]>("/api/v1/compliance/decisions") });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<any>("/api/v1/settings") });
  const auth = settings.data?.project.settings.india_authorization_status;

  return (
    <>
      <PageHeader title="Compliance" subtitle="Deterministic policy rules are authoritative; an LLM may add advisory notes but can never override them. Outcome: any BLOCK → BLOCK, else any REVIEW → REVIEW, else PASS." />
      <Card className="mb-6 p-4">
        <div className="flex flex-wrap items-center gap-3 text-[13px]">
          <span className="font-semibold text-slate-800">Target platform authorization to solicit Indian residents:</span>
          <StatusBadge value={auth} />
          <span className="text-slate-500">EDUCATIONAL content may be publication-eligible. PROMOTIONAL content is <b>BLOCKED_PENDING_AUTHORIZATION</b> until legal verifies authorization (Settings).</span>
        </div>
      </Card>
      <Tabs tabs={[
        { key: "decisions", label: "Decisions", content: (
          <Card>
            {decisions.error && <div className="p-4"><ErrorState error={decisions.error} /></div>}
            {decisions.isLoading ? <Loading /> : !decisions.data?.length ? <Empty title="No compliance decisions yet" /> : (
              <Table>
                <thead><tr><Th>Article</Th><Th>Status</Th><Th>Eligibility</Th><Th>Flagged rules</Th><Th>Decided by</Th><Th>When</Th></tr></thead>
                <tbody>
                  {decisions.data.map((d) => {
                    const flagged = d.rule_results.filter((r) => !r.passed);
                    return (
                      <tr key={d.id} className="hover:bg-slate-50">
                        <Td>{d.article ? <Link href={`/content/${d.article_id}`} className="font-medium text-slate-900 hover:text-indigo-700">{d.article.title}</Link> : "—"}
                          <div className="mt-1 flex gap-1">{d.article && <LangBadge lang={d.article.language} />}{d.article?.is_test_fixture && <Badge tone="red">RED-TEAM</Badge>}</div></Td>
                        <Td><StatusBadge value={d.status} /></Td>
                        <Td className="text-xs"><StatusBadge value={d.publication_eligibility} /></Td>
                        <Td className="max-w-sm text-xs">{flagged.length ? flagged.map((r) => <div key={r.rule_id}><span className={r.outcome === "BLOCK" ? "text-rose-600" : "text-amber-600"}>{r.rule_id}</span> {r.name}</div>) : <span className="text-emerald-600">all {d.rule_results.length} rules passed</span>}</Td>
                        <Td className="text-xs">{d.decided_by}</Td>
                        <Td className="text-xs">{fmtTime(d.created_at)}</Td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
            )}
          </Card>
        ) },
        { key: "sandbox", label: "Policy sandbox", content: <Sandbox /> },
        { key: "rules", label: `Rule catalog (${rules.data?.length ?? 0})`, content: (
          <Card>
            <Table>
              <thead><tr><Th>Rule</Th><Th>Category</Th><Th>Severity on fail</Th><Th>Description</Th></tr></thead>
              <tbody>{rules.data?.map((r) => (
                <tr key={r.rule_id}><Td><span className="font-mono text-xs text-slate-400">{r.rule_id}</span> <span className="font-medium text-slate-800">{r.name}</span></Td>
                  <Td>{r.category}</Td><Td><StatusBadge value={r.severity} /></Td><Td className="text-xs text-slate-600">{r.description}</Td></tr>
              ))}</tbody>
            </Table>
          </Card>
        ) },
      ]} />
    </>
  );
}
