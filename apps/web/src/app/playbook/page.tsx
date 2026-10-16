import { Card, CardHeader, PageHeader } from "@/components/ui";

export const metadata = { title: "SEO Playbook" };

const PILLARS: { title: string; points: string[] }[] = [
  { title: "Search-intent alignment", points: [
    "One canonical intent → one URL (enforced by DB reservation). Variants become sections of the existing page, never competing URLs.",
    "Intent type drives format: troubleshooting → ordered steps; commercial investigation → verifiable comparison framework; news → dated analysis with right of reply.",
    "SERP gap analysis shapes the outline (e.g. no Hindi result explains the RBI Alert List → our Hindi page leads with it).",
  ] },
  { title: "Evidence-backed, original content", points: [
    "Primary regulator/government sources first; every number cited or labelled illustrative; unverifiable broker facts omitted.",
    "Comparison pages publish the method and label unverified cells instead of inventing spreads or withdrawal times.",
    "Original research where possible: structured surveys of Indian traders, documented cost tests (with methodology), regulator-list change tracking.",
  ] },
  { title: "Topical authority & internal links", points: [
    "Hub-and-spoke: legality/regulation hub ↔ withdrawal, login, costs, alternatives spokes.",
    "New pages link to earlier relevant pages with descriptive, in-language anchors; reverse links are queued for the next refresh of older pages.",
    "No forced links: a relevance threshold blocks off-topic links; blocked/review drafts are never link targets.",
  ] },
  { title: "Multilingual targeting (en-IN · hi-IN)", points: [
    "Separate Hindi (Devanagari) pages on /hi-in/ with reciprocal hreflang to en-IN alternates of the same intent and x-default.",
    "Hinglish pages target Latin-script Hindi queries; tagged hi-Latn internally and served to the en-IN audience.",
    "Same intent in another language is a LOCALE VARIANT (hreflang alternate), not a cannibalising duplicate.",
  ] },
  { title: "Structured data", points: [
    "Article / NewsArticle with dateModified on refresh, FAQPage for genuine Q&A, BreadcrumbList for hierarchy.",
    "Markup mirrors visible content only. HowTo rich results are deprecated - steps stay as plain ordered lists.",
  ] },
  { title: "Mobile performance & Core Web Vitals", points: [
    "SSR/SSG HTML; LCP < 2.5 s, INP < 200 ms, CLS < 0.1 on mid-range Android over 4G.",
    "Devanagari font subsetting + font-display: swap; AVIF/WebP images with dimensions; lazy-load below the fold.",
    "Comparison tables scroll horizontally on mobile with a sticky first column.",
  ] },
  { title: "Content refreshes", points: [
    "UPDATE_EXISTING recommendations from the cannibalization engine feed a refresh queue (e.g. add an Exness section to the generic withdrawal guide).",
    "Regulatory snapshots are re-verified on a schedule; refreshed pages keep their URL and bump dateModified + version.",
  ] },
  { title: "Legitimate authority building (backlinks)", points: [
    "Digital PR: publish data-led studies (e.g. 'what Indian traders don't know about the RBI Alert List') and pitch financial journalists.",
    "Resource outreach: offer the Hindi legality guide to investor-education NGOs, university finance clubs and personal-finance creators as a free reference.",
    "Partner mentions: co-authored explainers with compliance lawyers or SEBI-registered educators, with clear disclosure.",
    "Expert commentary (journalist request platforms) on regulatory news; broken-link reclamation on pages citing outdated regulator URLs.",
  ] },
];

const NEVER = [
  "Spam links, PBNs or paid link schemes", "Fake reviews, testimonials or ratings", "Cloaking or bot-only content",
  "Doorway pages for keyword variants", "Competitor impersonation or competitor logos", "Promising '#1 rankings' or guaranteed profits",
];

export default function Playbook() {
  return (
    <>
      <PageHeader title="SEO Playbook" subtitle="How ATLAS aims to improve rankings through legitimate SEO. Ranking is an optimisation objective - never a guarantee." />
      <div className="grid gap-6 lg:grid-cols-2">
        {PILLARS.map((p) => (
          <Card key={p.title}>
            <CardHeader title={p.title} />
            <ul className="space-y-2 p-5 text-[13.5px] leading-relaxed text-slate-700">{p.points.map((x) => <li key={x}>• {x}</li>)}</ul>
          </Card>
        ))}
        <Card className="border-rose-200 lg:col-span-2">
          <CardHeader title="What ATLAS will never do" />
          <ul className="grid gap-2 p-5 text-[13.5px] text-rose-800 sm:grid-cols-2 lg:grid-cols-3">{NEVER.map((x) => <li key={x}>✕ {x}</li>)}</ul>
        </Card>
      </div>
    </>
  );
}
