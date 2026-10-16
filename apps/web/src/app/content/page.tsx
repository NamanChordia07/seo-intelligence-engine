"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { LinkGraph } from "@/components/link-graph";
import { Badge, Card, CardHeader, Empty, ErrorState, LangBadge, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { api, type ArticleSummary } from "@/lib/api";

export default function Content() {
  const arts = useQuery({ queryKey: ["articles"], queryFn: () => api<ArticleSummary[]>("/api/v1/articles") });
  const graph = useQuery({ queryKey: ["links"], queryFn: () => api<{ nodes: any[]; edges: any[] }>("/api/v1/internal-links") });
  const generated = (arts.data ?? []).filter((a) => a.origin === "GENERATED");
  const inventory = (arts.data ?? []).filter((a) => a.origin === "INVENTORY");

  return (
    <>
      <PageHeader title="Content" subtitle="Publication-ready Markdown drafts with frontmatter, citations, FAQ, internal links, SEO metadata and compliance status. Nothing is published - drafts are stored in PostgreSQL and outputs/articles/." />
      {arts.error && <ErrorState error={arts.error} />}
      {arts.isLoading ? <Loading /> : generated.length === 0 ? (
        <Card><Empty title="No generated articles yet" hint="Run Day 1 from the Overview page." /></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="article-grid">
          {generated.map((a) => (
            <Link key={a.id} href={`/content/${a.id}`} data-testid="article-card"
              className={`group flex flex-col rounded-xl border bg-white p-4 shadow-sm transition hover:border-indigo-300 hover:shadow ${a.is_test_fixture ? "border-rose-200" : "border-slate-200"}`}>
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge>Day {a.sim_day}</Badge><LangBadge lang={a.language} /><Badge tone="slate">{a.content_type.replaceAll("_", " ")}</Badge>
                {a.is_test_fixture && <Badge tone="red">RED-TEAM FIXTURE</Badge>}
              </div>
              <div className="mt-3 line-clamp-2 font-semibold leading-snug text-slate-900 group-hover:text-indigo-700">{a.title}</div>
              <div className="mt-1 truncate text-xs text-slate-500">/{a.slug}</div>
              <div className="mt-1 text-xs text-slate-500">keyword: {a.target_keyword}</div>
              <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-4">
                <StatusBadge value={a.compliance_status} /><StatusBadge value={a.status} />
                <span className="ml-auto text-[11px] text-slate-400">{a.publication_eligibility.replaceAll("_", " ")}</span>
              </div>
            </Link>
          ))}
        </div>
      )}

      <Card className="mt-6">
        <CardHeader title="Internal link architecture" subtitle="New pages link back to earlier relevant pages (Day 2 → Day 1, Day 3 → Day 1/2 and existing inventory). Irrelevant links are never forced." />
        <div className="p-4">{graph.data ? <LinkGraph nodes={graph.data.nodes} edges={graph.data.edges} /> : <Loading />}</div>
      </Card>

      {inventory.length > 0 && (
        <Card className="mt-6">
          <CardHeader title="Existing site inventory (simulated)" subtitle="Pre-existing pages used for cannibalization checks and as link targets." />
          <ul className="divide-y divide-slate-100">
            {inventory.map((a) => (
              <li key={a.id} className="flex items-center justify-between px-5 py-2.5 text-sm">
                <Link href={`/content/${a.id}`} className="font-medium text-slate-800 hover:text-indigo-700">{a.title}</Link>
                <span className="flex gap-1.5"><code className="text-xs text-slate-500">{a.intent_key}</code><Badge tone="blue">INVENTORY</Badge></span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
