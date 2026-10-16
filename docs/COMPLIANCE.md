# Compliance & Quality Architecture

## Principles

1. **Deterministic rules are authoritative.** `packages/domain/compliance.py` decides the status. An optional LLM
   reviewer (`ATLAS_LLM_ADVISORY_REVIEW=true`) can only attach advisory notes (`llm_advisory`).
2. **Educational ≠ promotional.** Content class is decided by the planner (bonus/solicitation themes are
   `PROMOTIONAL`) and gated separately from quality rules.
3. **Authorization is not assumed.** The project setting `india_authorization_status` defaults to `UNKNOWN`
   because RBI permits residents to trade forex only with authorised entities on authorised ETPs or recognised
   exchanges. While `UNKNOWN`, promotional content is `BLOCKED_PENDING_AUTHORIZATION` and can never be approved.
4. **Conservative facts.** No broker property is asserted without evidence; conflicting third-party data is
   labelled `CONFLICTING`/`UNVERIFIED` and triggers review.

## Outcome model

```
status      = BLOCK  if any rule outcome is BLOCK
            = REVIEW if any rule outcome is REVIEW
            = PASS   otherwise
eligibility = BLOCKED                         if status = BLOCK
            = BLOCKED_PENDING_AUTHORIZATION   if PROMOTIONAL and authorization ≠ VERIFIED
            = ELIGIBLE_EDUCATIONAL            if EDUCATIONAL and PASS
            = REQUIRES_HUMAN_REVIEW           otherwise
```

Article status: PASS → `APPROVED` (auto, educational only), REVIEW → `IN_REVIEW`, BLOCK → `BLOCKED`.
Human approval (`POST /articles/{id}/approve`, reviewer + note) is allowed for REVIEW only, recorded as a
`ComplianceDecision` with `decided_by = human:<name>`, an audit event and a ledger row. It survives re-validation
of the same version while the deterministic outcome stays REVIEW.

## Rules

| ID | Rule | Fails as | Notes |
|---|---|---|---|
| CMP-001 | Prohibited claims | BLOCK | guaranteed profit/returns, risk-free, no/zero risk, sure profit, assured returns, 100% safe, can't lose, double your money; Hindi (गारंटीड मुनाफा, बिना जोखिम, जोखिम-मुक्त, पक्का मुनाफा) and Hinglish (pakka profit, guaranteed munafa, bina risk, paisa double). Cautionary/negated mentions ("beware of anyone promising guaranteed returns") are allowed and counted. |
| CMP-002 | Risk warning present | BLOCK | Language-specific CFD/forex warning (EN/HI/Hinglish) |
| CMP-003 | Citation integrity | BLOCK | every footnote defined; every cited URL must exist in the evidence bundle → catches fabricated sources |
| CMP-004 | Sources present | REVIEW (0 → BLOCK) | ≥ 2 sources |
| CMP-005 | Regulatory statements cited | REVIEW | paragraphs mentioning RBI/SEBI/FEMA/ED/ESMA/FCA/CySEC need a citation |
| CMP-006 | No fabricated numbers | REVIEW | %, ₹/$/€ amounts, crore/lakh, pips, leverage ratios must be cited or in an "illustrative example" paragraph |
| CMP-007 | Unverified claims | REVIEW | relies on evidence marked UNVERIFIED / CONFLICTING |
| CMP-008 | No fake reviews | BLOCK | first-person trading testimonials, star ratings, "our users love" (EN/HI/Hinglish) |
| CMP-009 | No competitor logos | BLOCK | images whose alt/src mention a broker or "logo" |
| CMP-010 | Promotional tone | REVIEW (> 3/100 words → BLOCK) | density of promo words |
| CMP-011 | CTA policy | BLOCK in educational | account-opening / deposit / bonus solicitation; promotional → depends on authorization |
| CMP-012 | Misleading regulatory endorsement | BLOCK | "RBI approved", "SEBI registered", "legal in India" about a broker without negation |
| CMP-013 | Comparison claims | BLOCK / REVIEW | superlatives about named brokers block; uncited comparatives review |
| CMP-014 | Content depth | REVIEW (< 250 words → BLOCK) | ≥ 600 words, ≥ 3 sections |
| CMP-015 | Duplicate content | REVIEW > 0.25 · BLOCK > 0.5 | 5-gram Jaccard vs every other article |
| CMP-016 | Repetitive AI text | REVIEW | AI clichés, repeated sentences, over-repeated 4-grams |
| CMP-017 | Cannibalization | REVIEW / BLOCK | must hold a DB intent reservation and a NEW_PAGE_OK decision |
| CMP-018 | Named third-party review | REVIEW | comparisons / news / alternatives naming brokers need editorial-legal sign-off |
| CMP-019 | Promotional authorization gate | REVIEW / BLOCK | promotional content needs VERIFIED authorization |

A rule that throws is recorded as REVIEW ("Rule error") — a broken rule can never silently pass.

## Demonstrations

* **Red-team fixture** (`data/fixtures/content/adversarial-bonus-exness.yaml`) is injected on Day 2 as a raw,
  unsafe LLM output ("Earn guaranteed profits with zero risk", fake ₹50,000 testimonial, logo, "RBI approved",
  fabricated source, solicitation CTA). It is BLOCKED by CMP-001/002/003/008/009/010/012/013/014 and appears in
  the ledger as `REDTEAM_BLOCKED`. It is excluded from page counts and never used as a link target.
* **Policy sandbox** (Compliance → Policy sandbox, `POST /api/v1/compliance/check`) runs the engine on any text.
* **Local LLM check**: a real `llama3.2:3b` draft validated against the schema but contained no citations — the
  gate would block it (CMP-004), which is exactly why model output is never trusted directly.

## Limits

Regex/lexicon rules reduce but do not eliminate risk; they are tuned to be conservative (false REVIEWs are
preferred to false PASSes). Legal sign-off remains required for anything promotional or about named entities.
