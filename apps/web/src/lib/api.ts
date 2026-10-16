export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
export const TEMPORAL_UI_URL = process.env.NEXT_PUBLIC_TEMPORAL_UI_URL ?? "http://127.0.0.1:8233";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `Cannot reach the ATLAS API at ${API_URL}. Is it running?`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T,>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(body) });

// ---------------------------------------------------------------- types
export type Run = {
  id: string;
  parent_run_id: string | null;
  kind: string;
  sim_day: number | null;
  plan_date: string | null;
  status: string;
  orchestrator: string;
  temporal_workflow_id: string | null;
  provider_mode: string;
  trigger: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  stats: Record<string, any>;
  created_at: string;
};

export type DayStatus = {
  day: number;
  date: string;
  narrative: string;
  runs: number;
  latest_run_id: string | null;
  status: string;
  articles: number;
  redteam_articles: number;
  observations_fixture: number;
  data_label: string;
};

export type Dashboard = {
  project: { id: string; name: string; domain: string; settings: Record<string, any> };
  counts: Record<string, number>;
  observations_by_language: Record<string, number>;
  observations_by_source_type: Record<string, number>;
  opportunities_by_status: Record<string, number>;
  articles_by_language: Record<string, number>;
  compliance: Record<string, number>;
  recent_runs: Run[];
  top_opportunities: { id: string; keyword: string; language: string; score: number; why: string[]; sim_day: number; article_id: string | null }[];
  days: DayStatus[];
  data_label: string;
};

export type ScoreComponent = {
  key: string;
  label: string;
  value: number;
  weight: number;
  contribution: number;
  source_type: string;
  explanation: string;
};

export type CannCheck = {
  check: string;
  score: number;
  threshold: number;
  triggered: boolean;
  against_label: string | null;
  against_article_id: string | null;
  detail: string;
};

export type Opportunity = {
  id: string;
  run_id: string;
  candidate_id: string;
  sim_day: number | null;
  intent_key: string;
  keyword: string;
  language: string;
  locale: string;
  theme: string;
  intent: string;
  content_type: string;
  content_class: string;
  score: number;
  components: ScoreComponent[];
  why: string[];
  status: string;
  status_reason: string | null;
  cannibalization: { decision: string; reason: string; checks: CannCheck[]; conflicting_article_id?: string | null };
  conflicting_article_id: string | null;
  rank: number | null;
  article_id: string | null;
  created_at: string;
};

export type ArticleSummary = {
  id: string;
  origin: string;
  sim_day: number | null;
  slug: string;
  title: string;
  target_keyword: string;
  language: string;
  locale: string;
  theme: string;
  intent: string;
  intent_key: string;
  content_type: string;
  content_class: string;
  status: string;
  compliance_status: string;
  publication_eligibility: string;
  current_version: number;
  opportunity_score: number | null;
  is_test_fixture: boolean;
  file_path: string | null;
  created_at: string;
  updated_at: string;
};

export type RuleResult = {
  rule_id: string;
  name: string;
  category: string;
  severity_on_fail: string;
  passed: boolean;
  outcome: string | null;
  message: string;
  evidence: string[];
};

export type Decision = {
  id: string;
  article_id: string | null;
  article_version: number | null;
  status: string;
  publication_eligibility: string;
  content_class: string;
  rule_results: RuleResult[];
  reasons: string[];
  llm_advisory: Record<string, any> | null;
  decided_by: string;
  reviewer_note: string | null;
  created_at: string;
  article?: { title: string; slug: string; language: string; is_test_fixture: boolean } | null;
};

export type LinkRow = {
  id: string;
  article_id: string;
  title: string;
  slug: string;
  language: string;
  origin: string;
  path: string;
  anchor_text: string;
  score: number;
  reason: string;
  direction: string;
  status: string;
};

export type ArticleDetail = {
  article: ArticleSummary;
  path: string;
  version: {
    version: number;
    markdown: string;
    frontmatter: Record<string, any>;
    seo: Record<string, any>;
    brief: Record<string, any>;
    word_count: number;
    content_hash: string;
    generator: string;
    change_note: string | null;
    created_at: string;
  };
  versions: { version: number; generator: string; word_count: number; content_hash: string; change_note: string | null; created_at: string }[];
  links_out: LinkRow[];
  links_in: LinkRow[];
  compliance: Decision | null;
  opportunity: { id: string; score: number; why: string[]; components: ScoreComponent[]; cannibalization: any } | null;
};

export type EvidenceSource = {
  id: string;
  key: string;
  url: string;
  title: string;
  publisher: string;
  source_type: string;
  source_class: string;
  retrieval_mode: string;
  retrieved_at: string;
  published_at: string | null;
  snippet: string;
  content_hash: string;
  live_status: Record<string, any>;
  claims: { key: string; claim: string; claim_type: string; confidence: number; verification_status: string }[];
};

export type AuditEvent = {
  id: string;
  event_type: string;
  actor: string;
  message: string;
  payload: Record<string, any>;
  run_id: string | null;
  article_id: string | null;
  created_at: string;
};

export type Health = {
  status: string;
  database: boolean;
  temporal: string;
  orchestrator: string;
  provider_mode: string;
  llm_provider: string;
  version: string;
};

export const LANG_LABEL: Record<string, string> = { en: "English", hi: "Hindi", "hi-Latn": "Hinglish" };
