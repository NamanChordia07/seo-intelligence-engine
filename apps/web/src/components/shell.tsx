"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Activity, BookOpen, FileText, LayoutDashboard, Menu, Radar, ScrollText, Settings, ShieldCheck, Target, Workflow, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useState } from "react";

import { api, type Health } from "@/lib/api";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/search", label: "Search Intelligence", icon: Radar },
  { href: "/opportunities", label: "Opportunities", icon: Target },
  { href: "/content", label: "Content", icon: FileText },
  { href: "/workflows", label: "Workflows", icon: Workflow },
  { href: "/compliance", label: "Compliance", icon: ShieldCheck },
  { href: "/ledger", label: "Audit / Ledger", icon: ScrollText },
  { href: "/playbook", label: "SEO Playbook", icon: BookOpen },
  { href: "/settings", label: "Settings", icon: Settings },
];

function HealthPill() {
  const { data, isError } = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/health"), refetchInterval: 15000 });
  if (isError) return <span className="inline-flex items-center gap-1.5 text-xs text-rose-600"><span className="h-2 w-2 rounded-full bg-rose-500" />API offline</span>;
  if (!data) return null;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-600" title={data.temporal}>
      <span className={clsx("h-2 w-2 rounded-full", data.database ? "bg-emerald-500" : "bg-amber-500")} />
      {data.orchestrator === "temporal" ? "Temporal" : "Inline"} orchestrator · {data.llm_provider === "demo" ? "Demo LLM" : data.llm_provider}
    </span>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const active = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  const nav = (
    <nav className="flex flex-col gap-0.5 px-3" aria-label="Main">
      {NAV.map(({ href, label, icon: Icon }) => (
        <Link
          key={href}
          href={href}
          onClick={() => setOpen(false)}
          className={clsx(
            "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium transition-colors",
            active(href) ? "bg-white/10 text-white" : "text-slate-400 hover:bg-white/5 hover:text-slate-200",
          )}
        >
          <Icon className="h-4 w-4" />
          {label}
        </Link>
      ))}
    </nav>
  );

  const brand = (
    <div className="flex items-center gap-2.5 px-5 py-5">
      <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-indigo-400 to-violet-600 text-white shadow-inner">
        <Activity className="h-4 w-4" />
      </div>
      <div className="leading-tight">
        <div className="text-[15px] font-bold tracking-wide text-white">ATLAS</div>
        <div className="text-[10.5px] text-slate-400">Search Intelligence & Content Ops</div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen lg:pl-60">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col bg-[#0b1020] lg:flex">
        {brand}
        {nav}
        <div className="mt-auto space-y-1 border-t border-white/5 px-5 py-4 text-[11px] text-slate-500">
          <div>Project: India Trading Demo</div>
          <div>Locales: en-IN · hi-IN</div>
        </div>
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col bg-[#0b1020]">
            <div className="flex items-center justify-between pr-3">{brand}<button aria-label="Close menu" onClick={() => setOpen(false)} className="text-slate-400"><X className="h-5 w-5" /></button></div>
            {nav}
          </aside>
        </div>
      )}

      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-slate-200 bg-white/85 px-4 backdrop-blur sm:px-6">
        <button className="text-slate-600 lg:hidden" aria-label="Open menu" onClick={() => setOpen(true)}><Menu className="h-5 w-5" /></button>
        <span className="inline-flex items-center gap-1.5 rounded-md bg-violet-50 px-2 py-1 text-[11px] font-semibold text-violet-700 ring-1 ring-inset ring-violet-600/20">
          DEMO MODE · SIMULATED SIGNALS
        </span>
        <span className="hidden text-xs text-slate-500 md:inline">Evidence = snapshots of real public documents · Nothing is published</span>
        <div className="ml-auto"><HealthPill /></div>
      </header>

      <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:py-8">{children}</main>
    </div>
  );
}
