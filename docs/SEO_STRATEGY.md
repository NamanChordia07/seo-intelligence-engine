# SEO Strategy — how ATLAS aims to improve rankings legitimately

Ranking is an **optimisation objective**, not a promise. ATLAS improves the inputs search engines reward —
intent match, helpful evidence-backed content, site architecture and page experience — and refuses manipulative
tactics.

## 1. Search-intent alignment
* One canonical intent → one URL. Variants (broker-specific, year-suffixed, reordered comparisons) become sections
  of the existing page (`UPDATE_EXISTING`), not competing URLs.
* Format follows intent: troubleshooting → ordered steps; commercial investigation → verifiable comparison
  method; news → dated analysis with right of reply; legality → direct answer first.
* SERP gap analysis drives the outline (e.g. Hindi results lacked RBI Alert List / complaint routes → the Hindi
  guide leads with them).

## 2. Better, source-backed content
* Primary sources first (RBI, SEBI, ED, ESMA, government portals); every number cited or labelled illustrative;
  unverifiable broker facts omitted rather than guessed.
* Comparison pages publish their methodology and label unverified cells — more useful and more trustworthy than
  "winner" listicles.
* Original research opportunities: surveys of Indian traders' awareness of the RBI Alert List; documented,
  reproducible cost measurements with methodology; a changelog of regulator-list updates.

## 3. Topical authority & internal link architecture
* Hub: India legality/regulation. Spokes: withdrawals, login/security, trading costs, leverage, comparisons,
  news-led alternatives.
* Contextual in-body links with descriptive anchors in the page's language + a related-guides module.
* Reverse-link suggestions queue "add a link to the new page" for older pages' next refresh; orphan pages are
  avoided; low-relevance links are never forced.

## 4. Content refreshes
* `UPDATE_EXISTING` decisions form a refresh backlog with the triggering query attached.
* Regulatory snapshots are re-verified on a schedule; refreshed pages keep URL, bump version and `dateModified`.

## 5. Multilingual targeting (en-IN / hi-IN)
* `/en-in/guides/*` and `/hi-in/guides/*` sections, reciprocal `hreflang` for alternates of the same intent, plus
  `x-default`.
* Hindi pages are written natively in Devanagari (not machine-translated English); Hinglish pages capture
  Latin-script Hindi queries and are served to the en-IN audience (tagged `hi-Latn` internally).
* `LOCALE_VARIANT` decisions are the queue for creating proper hreflang pairs.

## 6. Structured data
* `Article`/`NewsArticle`, `FAQPage` (only for visible Q&A), `BreadcrumbList`. Markup mirrors on-page content.
* No HowTo markup reliance (rich result deprecated); steps remain semantic ordered lists.

## 7. Mobile performance & Core Web Vitals
* SSR/SSG HTML with JSON-LD in the initial response; targets LCP < 2.5 s, INP < 200 ms, CLS < 0.1 on mid-range
  Android over 4G.
* Devanagari font subsetting with `font-display: swap`; AVIF/WebP images with explicit dimensions; lazy-loading
  below the fold; horizontally scrollable tables with sticky first column.
* Canonical tags, XML sitemaps with `lastmod` per locale, robots: index educational pages, `noindex` drafts.

## 8. Legitimate authority building
* **Digital PR:** data-led studies (e.g. Indian traders' awareness of unauthorised-platform risks) pitched to
  personal-finance journalists.
* **Resource outreach:** offer the Hindi legality and withdrawal guides to investor-education NGOs, college
  finance clubs and creators as free references.
* **Partner mentions:** co-authored explainers with compliance lawyers / SEBI-registered educators, disclosed.
* **Expert commentary** on regulatory news via journalist-request platforms; broken-link reclamation where sites
  cite outdated regulator URLs.

## 9. What ATLAS will never do
Spam links, PBNs or paid link schemes · fake reviews/testimonials/ratings · cloaking · doorway pages for keyword
variants · competitor impersonation or logos · promises of "#1 rankings" or guaranteed profits.
