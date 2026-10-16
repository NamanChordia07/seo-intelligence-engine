"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import {
  Badge, Card, CardHeader, ErrorState, LangBadge, Loading, PageHeader, SourceBadge, StatusBadge, Table, Td, Th,
} from "@/components/ui";
import { api, type Opportunity } from "@/lib/api";

type Detail = {
  opportunity: Opportunity;
  serp: { query: string; source: string; source_type: string; results: any[]; analysis: any; captured_at: string } | null;
  brief: any;
  conflicting_article: { id: string; title: string; slug: string; language: string; origin: string } | null;
};

export default function OpportunityDetail() {
  const { id } = useParams<{ id: string }>();
  const { data, error, isLoading } = useQuery({ queryKey: ["opportunity", id], queryFn: () => api<Detail>(`/api/v1/opportunities/${id}`) });
  if (error) return <ErrorState error={error} />;
  if (isLoading || !data) return <Loading />;
  const o = data.opportunity;
  const pos = o.components.filter((c) => c.weight > 0);
  const neg = o.components.filter((c) => c.weight < 0);

  return (
    <>
      <Link href="/opportunities" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ArrowLeft className="h-4 w-4" /> Opportunities</Link>
      <PageHeader
        title={o.keyword}
        subtitle={<span className="flex flex-wrap items-center gap-2"><LangBadge lang={o.language} /><code className="text-xs">{o.intent_key}</code><span>{o.intent.replaceAll("_", " ")}</span><span>· Day {o.sim_day} · rank #{o.rank}</span></span>}
        actions={<><StatusBadge value={o.status} />{o.article_id && <Link href={`/content/${o.article_id}`} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">Open article</Link>}</>}
      />

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader title={<span>Score breakdown · <span className="tabular-nums text-indigo-700">{o.score.toFixed(1)}</span>/100</span>}
            subtitle="score = Σ(component × weight) − penalties. Positive weights sum to 1.0." />
          <div className="space-y-3 p-5" data-testid="score-breakdown">
            {[...pos, ...neg].map((c) => (
              <div key={c.key}>
                <div className="flex items-center justify-between gap-2 text-[13px]">
                  <span className="font-medium text-slate-800">{c.label} <span className="text-xs font-normal text-slate-400">× {c.weight}</span></span>
                  <span className="flex items-center gap-2"><SourceBadge value={c.source_type} />
                    <span className={`w-14 text-right font-semibold tabular-nums ${c.contribution < 0 ? "text-rose-600" : "text-slate-800"}`}>{c.contribution > 0 ? "+" : ""}{c.contribution.toFixed(1)}</span></span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div className={`h-full rounded-full ${c.weight < 0 ? "bg-rose-400" : "bg-indigo-500"}`} style={{ width: `${c.value}%` }} />
                </div>
                <div className="mt-1 text-xs text-slate-500">{c.value.toFixed(0)}/100 — {c.explanation}</div>
              </div>
            ))}
          </div>
        </Card>
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader title="Why this topic?" />
            <ul className="space-y-1.5 p-5 text-[13px] text-slate-700">{o.why.map((w) => <li key={w}>• {w}</li>)}</ul>
            <div className="border-t border-slate-100 px-5 py-3 text-[13px]"><span className="font-medium">Decision:</span> {o.status_reason}</div>
          </Card>
          <Card>
            <CardHeader title="Cannibalization engine" subtitle={o.cannibalization.reason} action={<StatusBadge value={o.cannibalization.decision} />} />
            {data.conflicting_article && (
              <div className="border-b border-slate-100 px-5 py-3 text-[13px]">Conflicts with <Link className="font-medium text-indigo-700 hover:underline" href={`/content/${data.conflicting_article.id}`}>{data.conflicting_article.title}</Link> <Badge>{data.conflicting_article.origin}</Badge></div>
            )}
            <Table className="max-h-80">
              <thead><tr><Th>Check</Th><Th>Score / threshold</Th><Th>Against</Th></tr></thead>
              <tbody>
                {o.cannibalization.checks.length === 0 && <tr><Td colSpan={3} className="text-slate-400">No related inventory to compare.</Td></tr>}
                {o.cannibalization.checks.map((c, i) => (
                  <tr key={i}>
                    <Td className="whitespace-nowrap">{c.triggered ? <XCircle className="mr-1 inline h-3.5 w-3.5 text-rose-500" /> : <CheckCircle2 className="mr-1 inline h-3.5 w-3.5 text-emerald-500" />}{c.check}</Td>
                    <Td className="tabular-nums text-xs">{c.score.toFixed(2)} / {c.threshold}</Td>
                    <Td className="max-w-[220px] truncate text-xs text-slate-500" >{c.against_label}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        </div>
      </div>

      {data.serp && (
        <Card className="mt-6">
          <CardHeader title="SERP / competitor observation" subtitle={`Weakness ${data.serp.analysis.weakness} · competition proxy ${data.serp.analysis.competition_proxy} · gaps: ${data.serp.analysis.content_gaps.join(", ") || "none"}`} action={<SourceBadge value={data.serp.source_type} />} />
          <Table>
            <thead><tr><Th>#</Th><Th>Result</Th><Th>Type</Th><Th>Published</Th><Th>Words</Th><Th>FAQ</Th><Th>Authority proxy</Th><Th>Intent match</Th></tr></thead>
            <tbody>
              {data.serp.results.map((r: any) => (
                <tr key={r.position}>
                  <Td>{r.position}</Td>
                  <Td><div className="font-medium text-slate-800">{r.title}</div><div className="text-xs text-slate-400">{r.url}</div></Td>
                  <Td><Badge tone={["forum", "qa", "video", "social"].includes(r.page_type) ? "amber" : "slate"}>{r.page_type}</Badge></Td>
                  <Td>{r.published}</Td><Td className="tabular-nums">{r.word_count_estimate}</Td><Td>{r.has_faq ? "yes" : "no"}</Td>
                  <Td className="tabular-nums">{r.authority_proxy}</Td><Td className="tabular-nums">{r.intent_match}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <div className="px-5 py-3 text-xs text-slate-500">Domains use the reserved <code>.example</code> TLD: these SERPs are simulated demonstration observations.</div>
        </Card>
      )}

      {data.brief && (
        <Card className="mt-6">
          <CardHeader title="Content brief" subtitle={`${data.brief.recommended_title} · /${data.brief.slug}`} />
          <div className="grid gap-6 p-5 text-[13px] md:grid-cols-2">
            <div>
              <div className="font-semibold text-slate-800">Angle</div><p className="text-slate-600">{data.brief.angle}</p>
              <div className="mt-3 font-semibold text-slate-800">Audience</div><p className="text-slate-600">{data.brief.audience}</p>
              <div className="mt-3 font-semibold text-slate-800">Outline</div>
              <ol className="ml-5 list-decimal text-slate-600">{data.brief.outline.map((s: any) => <li key={s.heading}>{s.heading} <span className="text-slate-400">— {s.purpose}</span></li>)}</ol>
              <div className="mt-3 font-semibold text-slate-800">Questions to answer</div>
              <ul className="ml-5 list-disc text-slate-600">{data.brief.questions_to_answer.map((q: string) => <li key={q}>{q}</li>)}</ul>
            </div>
            <div>
              <div className="font-semibold text-slate-800">Sources required</div>
              <ul className="ml-5 list-disc text-slate-600">{data.brief.sources_required.map((q: string) => <li key={q}>{q}</li>)}</ul>
              <div className="mt-3 font-semibold text-slate-800">Internal links planned</div>
              <ul className="ml-5 list-disc text-slate-600">{data.brief.internal_links.length ? data.brief.internal_links.map((l: any) => <li key={l.target_slug}>{l.target_title} <span className="text-slate-400">({l.score}, {l.reason})</span></li>) : <li>None relevant yet (first pages)</li>}</ul>
              <div className="mt-3 font-semibold text-slate-800">Compliance considerations</div>
              <ul className="ml-5 list-disc text-slate-600">{data.brief.compliance_considerations.map((q: string) => <li key={q}>{q}</li>)}</ul>
              <div className="mt-3 font-semibold text-slate-800">CTA policy</div><p className="text-slate-600">{data.brief.cta_policy}</p>
              <div className="mt-3 font-semibold text-slate-800">Schema</div><p className="text-slate-600">{data.brief.schema_recommendations.join(" · ")}</p>
              <div className="mt-3 font-semibold text-slate-800">Locale</div><p className="text-slate-600">{data.brief.locale} · hreflang {data.brief.hreflang}</p>
            </div>
          </div>
        </Card>
      )}
    </>
  );
}
