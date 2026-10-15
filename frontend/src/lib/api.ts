// Client de l'API FastAPI (même origine : l'interface est servie sur /ui).

const KEY_STORAGE = "nexalis-api-key";

export function getApiKey(): string {
  try {
    return localStorage.getItem(KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

export function setApiKey(key: string): void {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key);
    else localStorage.removeItem(KEY_STORAGE);
  } catch {
    // stockage indisponible (navigation privée) : la clé reste valable pour cet onglet
  }
  window.dispatchEvent(new Event("nexalis-api-key"));
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function headers(json = false): HeadersInit {
  const h: Record<string, string> = {};
  const key = getApiKey();
  if (key) h["X-API-Key"] = key;
  if (json) h["Content-Type"] = "application/json";
  return h;
}

async function errorFrom(response: Response): Promise<ApiError> {
  let detail = `Erreur ${response.status}`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // corps non JSON
  }
  return new ApiError(response.status, detail);
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { headers: headers(), signal });
  if (!response.ok) throw await errorFrom(response);
  return response.json() as Promise<T>;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await errorFrom(response);
  return response.json() as Promise<T>;
}

/** Envoi multipart (fichier + champs) : le navigateur fixe lui-même le Content-Type. */
export async function postForm<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(path, { method: "POST", headers: headers(), body: form });
  if (!response.ok) throw await errorFrom(response);
  return response.json() as Promise<T>;
}

export async function deleteRequest(path: string): Promise<void> {
  const response = await fetch(path, { method: "DELETE", headers: headers() });
  if (!response.ok) throw await errorFrom(response);
}

// ---------------------------------------------------------------- types de l'API

export interface Source {
  document: string;
  titre: string | null;
  section: string | null;
  page: number | null;
  score: number | null;
  extrait: string | null;
}

export interface StreamDone {
  answer: string;
  sources: Source[];
  timings_ms: Record<string, number>;
  request_id: string;
}

export type StreamEvent =
  | { type: "sources"; sources: Source[] }
  | { type: "token"; text: string }
  | { type: "done"; data: StreamDone }
  | { type: "error"; detail: string };

/** POST /ask/stream : lit le flux Server-Sent Events et appelle onEvent pour chaque événement. */
export async function askStream(
  question: string,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch("/ask/stream", {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify({ question }),
    signal,
  });
  if (!response.ok || !response.body) throw await errorFrom(response);

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
      const event = /^event: (.+)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (!event || data === undefined) continue;
      const payload = JSON.parse(data);
      if (event === "sources") onEvent({ type: "sources", sources: payload });
      else if (event === "token") onEvent({ type: "token", text: payload.text });
      else if (event === "done") onEvent({ type: "done", data: payload });
      else if (event === "error") onEvent({ type: "error", detail: payload.detail });
    }
  }
}

export interface Health {
  status: string;
  version: string;
  environment: string;
  llm_provider: string;
  llm_model: string;
  rag_enabled: boolean;
  indexed_chunks: number | null;
}

export interface Config {
  version: string;
  environment: string;
  prompt_version: string;
  llm: { provider: string; model: string; temperature: number; max_tokens: number; context: number | null };
  retrieval: {
    enabled: boolean;
    embedding_model: string;
    hybrid_search: boolean;
    lexical_weight: number;
    reranker: string | null;
    fetch_k: number;
    top_k: number;
    min_score: number;
    exclude_obsolete: boolean;
  };
  chunking: { size: number; overlap: number; min_tokens: number };
  security: { auth_enabled: boolean; rate_limit_per_minute: number; pii_filter: boolean };
  tracking: { mlflow: boolean };
}

export interface DocumentInfo {
  document: string;
  titre: string | null;
  format: string | null;
  categorie: string | null;
  version: string | null;
  date_effet: string | null;
  statut: string | null;
  sources: string;
  chunks: number | null;
  tokens: number | null;
  pages: number | null;
  /** « corpus » : corpus de référence ; « interface » : ajouté par un admin depuis le site. */
  origine: "corpus" | "interface";
  ajoute_le: string | null;
}

export interface WhoAmI {
  role: "employe" | "admin";
  auth_enabled: boolean;
  environment: string;
  upload: { docling: boolean; max_mb: number };
}

export interface UploadResult {
  document: string;
  format: string;
  chunks: number;
  seconds: number;
}

export interface ChunkInfo {
  index: number;
  section: string | null;
  page: number | null;
  tokens: number;
  text: string;
}

export interface LatencyStat {
  p50: number;
  p95: number;
  mean: number;
  count: number;
}

export interface MonitoringRow {
  request_id: string;
  time: number;
  endpoint: string;
  status: string;
  refused: boolean;
  llm_called: boolean;
  total_ms: number | null;
  llm_ms: number | null;
  n_sources: number | null;
  top_score: number | null;
  feedback: number | null;
}

export interface Monitoring {
  available: boolean;
  reason?: string;
  total?: number;
  statuses?: Record<string, number>;
  refusal_rate?: number | null;
  llm_call_rate?: number | null;
  mean_top_score?: number | null;
  mean_prompt_tokens?: number | null;
  feedback?: { positive: number; negative: number };
  latency?: Record<string, LatencyStat>;
  recent?: MonitoringRow[];
}

// ---------------------------------------------------------------- rapport d'évaluation

export interface RetrievalRow {
  dataset: string;
  chunk_size: string;
  overlap: number;
  hybrid: boolean;
  lexical_weight: number | null;
  reranker: string | null;
  recall_at_1: number;
  recall_at_3: number;
  recall_at_5: number;
  recall_at_8: number;
  mrr_at_10: number;
  ctx_tokens_at_5: number;
  latency_ms: number;
  n_chunks: number;
}

export interface AnswerItem {
  id: string;
  type: string;
  type_label: string;
  question: string;
  expected: string | null;
  document: string | null;
  answer: string | null;
  error: boolean;
  refused: boolean;
  llm_called: boolean;
  sources: string[];
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  status: "ok" | "ko" | "erreur";
  source_cited?: boolean;
  judge?: JudgeVerdict;
}

export interface JudgeVerdict {
  verdict: "correcte" | "partielle" | "incorrecte";
  exactitude: number;
  fidelite: number;
  citation: boolean;
  justification: string;
}

export interface JudgeSummary {
  judged: number;
  failed: number;
  verdicts: Record<"correcte" | "partielle" | "incorrecte", number>;
  correct_rate: number | null;
  exactitude_mean: number | null;
  fidelite_mean: number | null;
  citation_rate: number | null;
  agreement_keywords: number | null;
  kappa_keywords: number | null;
  disagreements: string[];
  tokens_in: number;
  tokens_out: number;
  cost_eur: number | null;
  judge_backend: string;
  judge_model: string;
  seconds: number;
  date: string;
}

export interface CostOption {
  key: string;
  label: string;
  model: string;
  billing: string;
  self_hosted: boolean;
  per_answer_eur: number;
  monthly_eur: number;
  note: string;
}

export interface Costs {
  volume: { users: number; questions: number; llm_share: number; days: number; hours: number; answers_per_month: number };
  measured: { prompt_tokens_mean: number; completion_tokens_mean: number; gpu_seconds_p50: number; answers: number; file: string };
  options: CostOption[];
  infrastructure: { label: string; monthly_eur: number };
  prices: { model: string; label: string; eur_per_m_input: number; eur_per_m_output: number; source: string }[];
  evaluation: {
    questions: number;
    gpu_seconds: number;
    gpu_eur_equivalent: number;
    judge_model: string | null;
    judge_eur: number | null;
    judge_tokens: number | null;
  };
  rate_source: string;
}

export interface AnswerSummary {
  generation_seconds_p50: number | null;
  evaluated: number;
  correct: number;
  accuracy: number;
  false_refusals: number;
  source_cited: number;
  oos_total: number;
  oos_refused: number;
  oos_without_llm: number;
  errors: number;
  latency_p50_ms: number | null;
  by_type: Record<string, { total: number; correct: number }>;
}

export interface AnswerRun {
  version: string;
  label: string;
  note: string;
  summary: AnswerSummary;
  items: AnswerItem[];
  judge?: JudgeSummary;
}

export interface QuantizationRow {
  backend: "ollama" | "zerogpu";
  model: string;
  questions: number;
  correct: number;
  accuracy: number;
  tokens_per_second: number | null;
  generation_seconds_p50?: number | null;
  prompt_seconds_p50?: number | null;
  llm_seconds_p50: number | null;
  vram_gb?: number | null;
  memory_gb?: number | null;
  gpu_share?: number | null;
}

export interface Report {
  generated_at: string;
  prompt_version: string;
  datasets: { syntec_questions: number; nexalis_questions: number; pii_messages: number };
  retained: {
    chunk_size: number;
    chunk_overlap: number;
    hybrid_search: boolean;
    lexical_weight: number;
    reranker: string | null;
    top_k: number;
    min_score: number;
    embedding_model: string;
    llm_model: string;
  };
  retrieval: {
    syntec_grid: RetrievalRow[];
    nexalis_sizes: RetrievalRow[];
    nexalis_sizes_minilm: RetrievalRow[];
    syntec_hybrid: RetrievalRow[];
    comparison: (RetrievalRow & { label: string; key: string })[];
    lexical_weights: RetrievalRow[];
    gating: { hybrid_search: boolean; questions: { id: string; type: string; in_scope: boolean; top_cosine: number }[] } | null;
    reranker_bench: {
      description: string;
      results: { model: string; params_millions: number; max_length: number; seconds_per_question: number }[];
    } | null;
  };
  answers: { runs: AnswerRun[]; type_labels: Record<string, string> };
  costs: Costs | null;
  quantization: QuantizationRow[];
  security: {
    messages: { id: string; type: string; label: string; detected: string[]; blocked: boolean; masked?: string }[];
    blocked: number;
    legit_questions: number;
    false_positives: number;
    labels: Record<string, string>;
  };
  tests: {
    timestamp: string;
    total: number;
    passed: number;
    failed: number;
    seconds: number;
    files: { file: string; tests: { name: string; status: string; seconds: number }[] }[];
  } | null;
}
