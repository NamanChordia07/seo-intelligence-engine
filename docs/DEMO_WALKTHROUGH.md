# Demo Walkthrough (5–10 minutes)

## Before the call (2 minutes)

```bash
python scripts/atlas.py up          # wait for "ATLAS is running"
```

Open three tabs: **http://127.0.0.1:3000** (app), **http://127.0.0.1:8233** (Temporal UI),
**http://127.0.0.1:8000/docs** (API). On the Overview page click **Reset demo → Confirm reset** so the
interviewer watches the days run live. (If anything misbehaves: `python scripts/atlas.py demo` runs all three
days from the CLI in ~15 s.)

---

## 1. Framing — Overview page (45 s)

**Point at:** the purple `DEMO MODE · SIMULATED SIGNALS` banner and the health pill (`Temporal orchestrator`).

> "ATLAS is a daily search-intelligence and content-operations pipeline for an India-focused trading platform.
> Two honesty rules run through the whole product: every signal carries provenance — SIMULATED, PROXY or
> REAL_PUBLIC — and nothing is ever published; it produces publication-ready drafts gated by compliance.
> No paid SEO APIs, no paid LLMs: it runs fully offline."

## 2. Run Day 1 (1 min)

**Click:** `Run Day 1`. Within ~5 s the card shows `COMPLETED · 2 new pages`.

> "That click started a Temporal `DailyIntelligenceWorkflow`: expand 350+ seed queries across English, Hindi and
> Hinglish, observe signals, normalise into language-agnostic intents, analyse SERPs, score, run the
> cannibalization engine, reserve intents in Postgres, then one child workflow per page: brief → research →
> draft → compliance → ledger."

**Click:** `View run →` — show the step timeline (discover → … → score_and_select) and the two child
`ArticleGenerationWorkflow`s. Optionally switch to the Temporal UI tab to show the same workflow history.

## 3. Why these pages? — Opportunities (1.5 min)

**Click:** sidebar `Opportunities` → filter `Day 1`.

> "Day 1 picked the **Hindi** legality question and the **Hinglish** withdrawal question. Notice the English and
> Hinglish legality queries are not separate pages — they're `LOCALE VARIANT`s: same intent, future hreflang
> alternates. 'is exness legal in india' is rejected because it overlaps today's legality page."

**Click** the top row → opportunity detail.

> "Every score is a weighted sum you can audit: demand proxy, trend, SERP weakness, relevance, freshness,
> content gap, minus competition, compliance risk and overlap. Each component says where it came from —
> SIMULATED here — and SERP metrics are ATLAS heuristics, explicitly not Google or Ahrefs numbers. The SERP
> table uses `.example` domains so simulated results can never be mistaken for real ones."

Scroll to **Content brief** (outline, sources required, compliance considerations, CTA policy, schema).

## 4. The content — Hindi article (1.5 min)

**Click:** `Open article`.

> "Publication-ready Markdown: frontmatter, H1, a mandatory Hindi risk warning, a table where every row is
> labelled `VERIFIED_SNAPSHOT`, FAQ, and footnoted sources — RBI's Alert List press release, RBI's forex FAQ,
> SEBI, the cybercrime portal."

**Click tabs:** `Evidence & sources` (claims + verification status + retrieval mode) → `SEO & schema`
(snippet preview, hreflang hi-IN + x-default, JSON-LD Article/FAQPage/BreadcrumbList, mobile/CWV checklist)
→ `Compliance` (19-rule checklist, all green).

## 5. Run Day 2 — linking, dedup and the red team (1.5 min)

**Back to Overview → click** `Run Day 2`. Card shows `2 new pages · 1 red-team draft blocked`.

> "Day 2 adds an Exness-vs-XM comparison and a login-troubleshooting page. Three things to notice."

1. **Opportunities, Day 2:** the Hindi legality duplicate → `UPDATE EXISTING` ("refresh the Day 1 page
   instead"); `exness withdrawal time` → update the Day 1 withdrawal guide.
2. **Content → comparison article:** "It refuses to invent spreads or withdrawal times. The table labels
   licence data `CONFLICTING` because third-party sources disagree, and the page is `REVIEW` — it names third
   parties, so legal signs off. Internal links point back to both Day 1 pages."
3. **Content → red-team card:** "We deliberately pushed an unsafe LLM-style draft through the same gate:
   'guaranteed profits with zero risk', a fake ₹50,000 testimonial, a broker logo, 'RBI approved', a fabricated
   source. It's BLOCKED by nine rules and can never be approved."

## 6. Run Day 3 — news-led + no cannibalization (1 min)

**Click** `Run Day 3`.

> "Day 3 is news-led: enforcement coverage drove 'OctaFX alternative' searches. Instead of steering readers to
> another offshore broker, the page summarises the ED's reported actions with the company's denial, then points
> to legal routes — exchange-traded currency derivatives via SEBI-registered brokers. Plus a Hindi
> trading-costs explainer whose numbers sit in a clearly labelled illustrative example."

**Opportunities, Day 3:** `xm vs exness` and `exness vs xm which is better` → `UPDATE EXISTING` (same
canonical intent as Day 2, order-independent). **Content → link graph:** Day 3 pages link back to Day 1/2 and to
the existing inventory page on leverage.

## 7. Prove the guarantees (45 s)

* **Re-run Day 1 (dup test)** on the Overview → finishes with **0 new pages**: everything maps to existing pages.
  > "Even a forced re-run can't create a duplicate — the intent reservation is a Postgres UNIQUE constraint."
* **Compliance → Policy sandbox → Run policy engine** on the unsafe sample → BLOCK, rule by rule.
* **Settings:** authorization is `UNKNOWN`. "Promotional content stays `BLOCKED_PENDING_AUTHORIZATION` until legal
  verifies the platform may solicit Indian residents. Educational content is unaffected."

## 8. The running sheet (30 s)

**Click:** `Audit / Ledger` → **Download CSV** (open in Excel — Hindi renders thanks to the UTF-8 BOM).

> "One row per page created, duplicate refused, compliance or approval decision: date, run ID, article ID,
> keyword, language, intent, score, slug, statuses, evidence sources, version, timestamps. Audit events tab is
> the full event log."

Optional: on the comparison article, **Compliance → Human approve** (reviewer + note) → status APPROVED, new
ledger row `HUMAN_APPROVED`.

## 9. Close (30 s)

> "Architecture: Next.js → FastAPI → Temporal workers → provider adapters → Postgres with pgvector. Deterministic
> code owns dedup, policy, state and retries; models are used for drafting and can be swapped — demo library,
> local Ollama, or any OpenAI-compatible API. To go to production: plug real data into the adapters (Search
> Console, licensed keyword data), swap in a neural multilingual embedder, scale workers per task queue, and
> connect a CMS behind the eligibility gate. Rankings are an optimisation objective — intent match, evidence,
> internal links and performance — never a guarantee."

---

### Likely questions

| Question | Answer |
|---|---|
| Are the volumes real? | No — SIMULATED relative indices, labelled everywhere. Live mode uses autocomplete presence (REAL_PUBLIC, no volume). Real volumes need Search Console or a licensed provider via the same adapter. |
| How do you stop duplicates? | Six independent checks (canonical intent key, keyword Jaccard, semantic cosine, entity subsumption, SERP overlap, slug) + DB UNIQUE reservation + per-day capacity accounting. |
| Why not let the LLM judge compliance? | LLMs are non-deterministic and unauditable; rules are authoritative, LLM advice is optional and advisory only. A real llama3.2 draft passed schema validation but had zero citations — the gate catches it. |
| What if Temporal is down? | `auto` mode detects no worker poller and runs the same activities inline; recorded on the run. |
| Hinglish hreflang? | Tagged `hi-Latn` internally, served to `en-IN`; Hindi pages are `hi-IN` with reciprocal alternates. |
