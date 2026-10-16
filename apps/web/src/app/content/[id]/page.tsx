"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, ExternalLink, RefreshCw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { RuleChecklist } from "@/components/rule-checklist";
import {
  Badge, Button, Card, CardHeader, ErrorState, LangBadge, Loading, PageHeader, SourceBadge, StatusBadge, Table, Tabs, Td, Th, fmtTime,
} from "@/components/ui";
import { API_URL, api, post, type ArticleDetail, type Decision, type EvidenceSource } from "@/lib/api";

function stripFrontmatter(md: string) {
  return md.replace(/^---\n[\s\S]*?\n---\n/, "");
}

function Preview({ d }: { d: ArticleDetail }) {
  const byPath = new Map(d.links_out.map((l) => [l.path, l.article_id]));
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_300px]">
      <article className="prose-atlas" lang={d.article.language === "hi" ? "hi" : "en"} data-testid="article-preview">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
          a: ({ href, children }) => {
            const target = href ? byPath.get(href) : undefined;
            if (target) return <Link href={`/content/${target}`} title={`Internal link → ${href}`}>{children}</Link>;
            return <a href={href} target={href?.startsWith("http") ? "_blank" : undefined} rel="noopener noreferrer">{children}</a>;
          },
        }}>{stripFrontmatter(d.version.markdown)}</ReactMarkdown>
      </article>
      <aside className="space-y-4">
        <Card className="p-4 text-[13px]">
          <div className="mb-2 font-semibold text-slate-800">Frontmatter</div>
          <dl className="space-y-1">
            {Object.entries(d.version.frontmatter).map(([k, v]) => (
              <div key={k} className="grid grid-cols-[110px_1fr] gap-2"><dt className="text-slate-400">{k}</dt><dd className="break-words text-slate-700">{String(v)}</dd></div>
            ))}
          </dl>
        </Card>
      </aside>
    </div>
  );
}

function Seo({ seo }: { seo: Record<string, any> }) {
  if (!seo || !seo.title) return <div className="text-sm text-slate-500">No SEO package (inventory page).</div>;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card className="p-5 text-[13px]">
        <div className="mb-3 font-semibold text-slate-800">Search snippet preview</div>
        <div className="rounded-lg border border-slate-200 p-3">
          <div className="text-xs text-slate-500">{seo.canonical}</div>
          <div className="text-[17px] leading-snug text-[#1a0dab]">{seo.title}</div>
          <div className="text-[13px] text-slate-600">{seo.meta_description}</div>
        </div>
        <div className="mt-4 space-y-1.5">
          {seo.checks.map((c: any) => (
            <div key={c.check} className="flex justify-between gap-2"><span className="text-slate-600">{c.check.replaceAll("_", " ")}</span>
              <span>{String(c.value)} {c.ok ? <Badge tone="green">ok</Badge> : <Badge tone="amber">{c.note}</Badge>}</span></div>
          ))}
        </div>
        <div className="mt-4 font-semibold text-slate-800">hreflang</div>
        <ul className="mt-1 space-y-0.5 font-mono text-xs">{seo.hreflang.map((h: any) => <li key={h.hreflang}>&lt;link rel=&quot;alternate&quot; hreflang=&quot;{h.hreflang}&quot; href=&quot;{h.href}&quot;&gt;</li>)}</ul>
        {seo.hreflang_note && <p className="mt-2 text-xs text-slate-500">{seo.hreflang_note}</p>}
        <div className="mt-4 font-semibold text-slate-800">Schema recommendations</div>
        <p className="text-slate-600">{seo.schema_recommendations.join(" · ")}</p>
        <p className="mt-4 rounded bg-slate-50 p-2 text-xs text-slate-500">{seo.ranking_note}</p>
      </Card>
      <Card className="p-5 text-[13px]">
        <div className="mb-2 font-semibold text-slate-800">JSON-LD (Article · FAQPage · BreadcrumbList)</div>
        <pre className="scrollbar-thin max-h-[420px] overflow-auto rounded-lg bg-slate-950 p-3 text-[11px] leading-relaxed text-slate-100">{JSON.stringify(seo.json_ld, null, 2)}</pre>
      </Card>
      <Card className="p-5 text-[13px] lg:col-span-2">
        <div className="mb-2 font-semibold text-slate-800">Technical SEO & mobile performance recommendations</div>
        <ul className="grid gap-2 md:grid-cols-2">{seo.technical.map((t: any) => <li key={t.area}><span className="font-medium text-slate-800">{t.area}:</span> <span className="text-slate-600">{t.item}</span></li>)}</ul>
      </Card>
    </div>
  );
}

function Evidence({ id }: { id: string }) {
  const { data, error, isLoading } = useQuery({ queryKey: ["evidence", id], queryFn: () => api<{ sources: EvidenceSource[]; gaps: string[]; note: string }>(`/api/v1/articles/${id}/evidence`) });
  if (error) return <ErrorState error={error} />;
  if (isLoading || !data) return <Loading />;
  return (
    <div className="space-y-4" data-testid="evidence-panel">
      <p className="text-[13px] text-slate-500">{data.note}</p>
      {data.gaps.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-[13px] text-amber-900">
          <div className="font-semibold">Evidence gaps (facts omitted or labelled unverified)</div>
          <ul className="mt-1 list-disc pl-5">{data.gaps.map((g) => <li key={g}>{g}</li>)}</ul>
        </div>
      )}
      {data.sources.length === 0 && <div className="text-sm text-slate-500">No evidence attached.</div>}
      {data.sources.map((s) => (
        <Card key={s.id} className="p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <a href={s.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-slate-900 hover:text-indigo-700">{s.title} <ExternalLink className="h-3 w-3" /></a>
              <div className="text-xs text-slate-500">{s.publisher}{s.published_at && ` · published ${s.published_at}`} · retrieved {fmtTime(s.retrieved_at)}</div>
              <div className="mt-0.5 break-all text-[11px] text-slate-400">{s.url}</div>
            </div>
            <div className="flex flex-wrap gap-1"><SourceBadge value={s.source_type} /><Badge tone="slate">{s.source_class.replaceAll("_", " ")}</Badge><Badge tone="blue">{s.retrieval_mode}</Badge></div>
          </div>
          <p className="mt-2 rounded bg-slate-50 p-2 text-[12.5px] italic text-slate-600">“{s.snippet}”</p>
          <Table className="mt-2">
            <thead><tr><Th>Claim supported</Th><Th>Type</Th><Th>Confidence</Th><Th>Verification</Th></tr></thead>
            <tbody>{s.claims.map((c) => (
              <tr key={c.key}><Td>{c.claim}</Td><Td>{c.claim_type}</Td><Td className="tabular-nums">{c.confidence}</Td><Td><StatusBadge value={c.verification_status} /></Td></tr>
            ))}</tbody>
          </Table>
        </Card>
      ))}
    </div>
  );
}

function ComplianceTab({ d, id }: { d: ArticleDetail; id: string }) {
  const qc = useQueryClient();
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const history = useQuery({ queryKey: ["compliance-history", id], queryFn: () => api<Decision[]>(`/api/v1/articles/${id}/compliance`) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["article", id] }); qc.invalidateQueries({ queryKey: ["compliance-history", id] }); };
  const validate = useMutation({ mutationFn: () => post<Decision>(`/api/v1/articles/${id}/validate`), onSuccess: (r) => { setMsg(`Re-validated: ${r.status}`); refresh(); }, onError: (e: Error) => setMsg(e.message) });
  const approve = useMutation({ mutationFn: () => post(`/api/v1/articles/${id}/approve`, { reviewer, note }), onSuccess: () => { setMsg("Approved by human reviewer - recorded in ledger and audit log."); refresh(); }, onError: (e: Error) => setMsg(e.message) });
  const c = d.compliance;
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
      <div>
        {c ? (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
              <StatusBadge value={c.status} /><StatusBadge value={c.publication_eligibility} /><Badge>{c.content_class}</Badge>
              <span className="text-xs text-slate-500">decided by {c.decided_by} · v{c.article_version} · {fmtTime(c.created_at)}</span>
            </div>
            <RuleChecklist results={c.rule_results} />
            {c.llm_advisory && <pre className="mt-3 rounded bg-slate-50 p-3 text-xs">{JSON.stringify(c.llm_advisory, null, 2)}</pre>}
          </>
        ) : <div className="text-sm text-slate-500">Not validated (inventory page).</div>}
      </div>
      {d.article.origin === "GENERATED" && (
        <div className="space-y-4">
          <Card className="p-4">
            <div className="text-sm font-semibold text-slate-800">Policy actions</div>
            <p className="mt-1 text-xs text-slate-500">Deterministic rules are authoritative. BLOCK can never be approved; promotional content needs VERIFIED India authorization.</p>
            <Button variant="secondary" className="mt-3 w-full" onClick={() => validate.mutate()} loading={validate.isPending}><RefreshCw className="h-3.5 w-3.5" /> Re-run compliance</Button>
            <div className="mt-4 space-y-2">
              <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Reviewer name" className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
              <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Review note (required)" rows={3} className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
              <Button className="w-full" onClick={() => approve.mutate()} loading={approve.isPending} disabled={reviewer.length < 2 || note.length < 3}><ShieldCheck className="h-3.5 w-3.5" /> Human approve</Button>
            </div>
            {msg && <div className="mt-3 rounded bg-slate-50 p-2 text-xs text-slate-700" role="status">{msg}</div>}
          </Card>
          <Card className="p-4">
            <div className="text-sm font-semibold text-slate-800">Decision history</div>
            <ul className="mt-2 space-y-2 text-xs">
              {history.data?.map((h) => <li key={h.id} className="flex items-center justify-between gap-2"><span className="truncate text-slate-600">{h.decided_by}</span><StatusBadge value={h.status} /></li>)}
            </ul>
          </Card>
        </div>
      )}
    </div>
  );
}

function Links({ d }: { d: ArticleDetail }) {
  const row = (l: ArticleDetail["links_out"][number]) => (
    <tr key={l.id}><Td><Link href={`/content/${l.article_id}`} className="font-medium text-indigo-700 hover:underline">{l.title}</Link><div className="text-[11px] text-slate-400">{l.path}</div></Td>
      <Td className="text-xs">{l.anchor_text}</Td><Td><StatusBadge value={l.direction} /></Td><Td className="tabular-nums">{l.score.toFixed(2)}</Td><Td className="text-xs text-slate-500">{l.reason}</Td></tr>
  );
  return (
    <div className="space-y-6">
      <Card><CardHeader title="Outbound links (this page → earlier pages)" />
        <Table><thead><tr><Th>Target</Th><Th>Anchor</Th><Th>Type</Th><Th>Score</Th><Th>Reason</Th></tr></thead><tbody>{d.links_out.length ? d.links_out.map(row) : <tr><Td colSpan={5} className="text-slate-400">No relevant earlier pages - links are never forced.</Td></tr>}</tbody></Table></Card>
      <Card><CardHeader title="Inbound links (later pages → this page)" subtitle="REVERSE SUGGESTED = add this link when the older page is next refreshed" />
        <Table><thead><tr><Th>Source</Th><Th>Anchor</Th><Th>Type</Th><Th>Score</Th><Th>Reason</Th></tr></thead><tbody>{d.links_in.length ? d.links_in.map(row) : <tr><Td colSpan={5} className="text-slate-400">None yet.</Td></tr>}</tbody></Table></Card>
    </div>
  );
}

export default function ArticlePage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, isLoading } = useQuery({ queryKey: ["article", id], queryFn: () => api<ArticleDetail>(`/api/v1/articles/${id}`) });
  if (error) return <ErrorState error={error} />;
  if (isLoading || !data) return <Loading />;
  const a = data.article;
  return (
    <>
      <Link href="/content" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ArrowLeft className="h-4 w-4" /> Content</Link>
      {a.is_test_fixture && (
        <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-[13px] text-rose-900">
          <b>ADVERSARIAL TEST FIXTURE.</b> An intentionally unsafe draft pushed through the same pipeline to prove the compliance gate blocks it. Not a real page.
        </div>
      )}
      <PageHeader
        title={a.title}
        subtitle={<span className="flex flex-wrap items-center gap-2"><LangBadge lang={a.language} /><span>{a.locale}</span><code className="text-xs">{data.path}</code>
          <span>· keyword “{a.target_keyword}” · {a.intent.replaceAll("_", " ")}</span>{a.sim_day && <Badge>Day {a.sim_day}</Badge>}</span>}
        actions={<>
          <StatusBadge value={a.compliance_status} /><StatusBadge value={a.publication_eligibility} />
          <a href={`${API_URL}/api/v1/articles/${a.id}/markdown`} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"><Download className="h-3.5 w-3.5" /> .md</a>
        </>}
      />
      <div className="mb-4 flex flex-wrap gap-4 text-xs text-slate-500">
        <span>v{data.version.version} · {data.version.word_count} words · generator: {data.version.generator}</span>
        <span>hash {data.version.content_hash.slice(0, 12)}</span>
        {a.file_path && <span>file: {a.file_path}</span>}
        {data.opportunity && <Link className="text-indigo-600 hover:underline" href={`/opportunities/${data.opportunity.id}`}>opportunity score {data.opportunity.score.toFixed(1)} →</Link>}
      </div>
      <Card className="p-5">
        <Tabs tabs={[
          { key: "preview", label: "Preview", content: <Preview d={data} /> },
          { key: "compliance", label: "Compliance", content: <ComplianceTab d={data} id={id} /> },
          { key: "evidence", label: "Evidence & sources", content: <Evidence id={id} /> },
          { key: "seo", label: "SEO & schema", content: <Seo seo={data.version.seo} /> },
          { key: "links", label: `Internal links (${data.links_out.length}/${data.links_in.length})`, content: <Links d={data} /> },
          { key: "markdown", label: "Markdown", content: <pre className="scrollbar-thin max-h-[640px] overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-4 font-mono text-[12px] leading-relaxed text-slate-100">{data.version.markdown}</pre> },
          { key: "versions", label: "Versions", content: (
            <Table><thead><tr><Th>Version</Th><Th>Generator</Th><Th>Words</Th><Th>Hash</Th><Th>Note</Th><Th>Created</Th></tr></thead>
              <tbody>{data.versions.map((v) => <tr key={v.version}><Td>v{v.version}</Td><Td>{v.generator}</Td><Td>{v.word_count}</Td><Td className="font-mono text-xs">{v.content_hash}</Td><Td className="text-xs">{v.change_note}</Td><Td>{fmtTime(v.created_at)}</Td></tr>)}</tbody></Table>
          ) },
        ]} />
      </Card>
    </>
  );
}
