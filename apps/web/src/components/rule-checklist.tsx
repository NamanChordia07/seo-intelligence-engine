"use client";

import { CheckCircle2, CircleAlert, XCircle } from "lucide-react";

import type { RuleResult } from "@/lib/api";

import { Badge } from "./ui";

export function RuleChecklist({ results }: { results: RuleResult[] }) {
  const ordered = [...results].sort((a, b) => Number(a.passed) - Number(b.passed) || (a.outcome === "BLOCK" ? -1 : 1));
  return (
    <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200" data-testid="rule-checklist">
      {ordered.map((r) => (
        <li key={r.rule_id} className="flex gap-3 px-4 py-2.5">
          {r.passed ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
            : r.outcome === "BLOCK" ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />
            : <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-[13px]">
              <span className="font-mono text-[11px] text-slate-400">{r.rule_id}</span>
              <span className="font-medium text-slate-800">{r.name}</span>
              <Badge tone="slate">{r.category}</Badge>
              {!r.passed && <Badge tone={r.outcome === "BLOCK" ? "red" : "amber"}>{r.outcome}</Badge>}
            </div>
            <div className="mt-0.5 text-[12.5px] text-slate-600">{r.message}</div>
            {!r.passed && r.evidence.length > 0 && (
              <ul className="mt-1 space-y-0.5">
                {r.evidence.slice(0, 4).map((e, i) => <li key={i} className="rounded bg-rose-50/60 px-2 py-0.5 font-mono text-[11px] text-rose-900">{e}</li>)}
              </ul>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
