"use client";

import clsx from "clsx";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useState } from "react";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("rounded-xl border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]", className)}>{children}</div>;
}

export function CardHeader({ title, subtitle, action }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold text-slate-900">{title}</h2>
        {subtitle && <p className="mt-0.5 text-[13px] text-slate-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const TONES: Record<string, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/25",
  red: "bg-rose-50 text-rose-700 ring-rose-600/20",
  blue: "bg-sky-50 text-sky-700 ring-sky-600/20",
  violet: "bg-violet-50 text-violet-700 ring-violet-600/20",
  slate: "bg-slate-100 text-slate-700 ring-slate-500/20",
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-600/20",
};

export function Badge({ tone = "slate", children, className, title }: { tone?: keyof typeof TONES | string; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset", TONES[tone] ?? TONES.slate, className)}>
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, string> = {
  PASS: "green", APPROVED: "green", COMPLETED: "green", SELECTED: "green", NEW_PAGE_OK: "green", ELIGIBLE_EDUCATIONAL: "green", PUBLISHED: "blue",
  VERIFIED_SNAPSHOT: "green", VERIFIED_LIVE: "green", VERIFIED: "green", INSERTED: "indigo",
  REVIEW: "amber", IN_REVIEW: "amber", PARTIAL: "amber", DEFERRED: "slate", UPDATE_EXISTING: "violet", UPDATE_EXISTING_PAGE: "violet",
  LOCALE_VARIANT: "blue", REQUIRES_HUMAN_REVIEW: "amber", UNVERIFIED: "amber", CONFLICTING: "amber", UNKNOWN: "amber", METHOD: "slate",
  BLOCK: "red", BLOCKED: "red", FAILED: "red", REJECTED: "red", REJECT_NEW_PAGE: "red", BLOCKED_PENDING_AUTHORIZATION: "red", NOT_AUTHORIZED: "red",
  RUNNING: "blue", QUEUED: "slate", DRAFT: "slate", PENDING: "slate", SKIPPED: "slate", RELATED_MODULE: "slate", REVERSE_SUGGESTED: "violet",
};

export function StatusBadge({ value, className }: { value: string | null | undefined; className?: string }) {
  if (!value) return null;
  const running = value === "RUNNING";
  return (
    <Badge tone={STATUS_TONE[value] ?? "slate"} className={className}>
      {running && <Loader2 className="h-3 w-3 animate-spin" />}
      {value.replaceAll("_", " ")}
    </Badge>
  );
}

const SOURCE_TONE: Record<string, string> = { SIMULATED: "violet", PROXY: "blue", REAL_PUBLIC: "green" };
export function SourceBadge({ value }: { value: string }) {
  const title =
    value === "SIMULATED" ? "Deterministic demonstration data - not a real observation"
    : value === "PROXY" ? "Heuristic estimate derived from observations - not an official metric"
    : "Observed from a real public source";
  return <Badge tone={SOURCE_TONE[value] ?? "slate"} title={title}>{value}</Badge>;
}

export function LangBadge({ lang }: { lang: string }) {
  const label = { en: "EN", hi: "HI", "hi-Latn": "Hinglish" }[lang] ?? lang;
  return <Badge tone={lang === "en" ? "slate" : lang === "hi" ? "amber" : "indigo"}>{label}</Badge>;
}

export function Button({ variant = "primary", loading, className, children, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-indigo-600 text-white shadow-sm hover:bg-indigo-700",
        variant === "secondary" && "border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50",
        variant === "ghost" && "text-slate-600 hover:bg-slate-100",
        variant === "danger" && "border border-rose-200 bg-white text-rose-700 hover:bg-rose-50",
        className,
      )}
    >
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
}

export function Stat({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-[12px] font-medium uppercase tracking-wide text-slate-500">
        {label}
        {icon && <span className="text-slate-400">{icon}</span>}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </Card>
  );
}

export function ScoreBar({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const color = value >= 65 ? "bg-emerald-500" : value >= 45 ? "bg-indigo-500" : "bg-slate-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
        <div className={clsx("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 text-right text-xs font-semibold tabular-nums text-slate-700">{value.toFixed(1)}</span>
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-8 text-sm text-slate-500">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}…
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800" role="alert">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div>{error instanceof Error ? error.message : String(error)}</div>
    </div>
  );
}

export function Empty({ title, hint, action }: { title: string; hint?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <Inbox className="h-8 w-8 text-slate-300" />
      <div className="text-sm font-medium text-slate-700">{title}</div>
      {hint && <div className="max-w-md text-sm text-slate-500">{hint}</div>}
      {action}
    </div>
  );
}

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx("scrollbar-thin overflow-x-auto", className)}>
      <table className="w-full min-w-[640px] border-collapse text-left text-[13px]">{children}</table>
    </div>
  );
}
export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return <th className={clsx("border-b border-slate-200 bg-slate-50/70 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500", className)}>{children}</th>;
}
export function Td({ children, className, colSpan }: { children?: ReactNode; className?: string; colSpan?: number }) {
  return <td colSpan={colSpan} className={clsx("border-b border-slate-100 px-3 py-2 align-top text-slate-700", className)}>{children}</td>;
}

export function Tabs({ tabs, initial }: { tabs: { key: string; label: ReactNode; content: ReactNode }[]; initial?: string }) {
  const [active, setActive] = useState(initial ?? tabs[0]?.key);
  return (
    <div>
      <div className="scrollbar-thin flex gap-1 overflow-x-auto border-b border-slate-200" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={active === t.key}
            onClick={() => setActive(t.key)}
            className={clsx(
              "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              active === t.key ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-800",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="pt-4">{tabs.find((t) => t.key === active)?.content}</div>
    </div>
  );
}

export function SimulatedNotice({ children }: { children?: ReactNode }) {
  return (
    <div className="mb-4 flex items-start gap-2 rounded-lg border border-violet-200 bg-violet-50/70 px-3 py-2 text-[13px] text-violet-900">
      <Badge tone="violet">SIMULATED</Badge>
      <span>{children ?? "Search signals and SERP observations on this page are deterministic demonstration data, not real search volumes or Google metrics."}</span>
    </div>
  );
}

export function fmtTime(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export function duration(a: string | null, b: string | null) {
  if (!a || !b) return "—";
  const ms = new Date(b).getTime() - new Date(a).getTime();
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}
