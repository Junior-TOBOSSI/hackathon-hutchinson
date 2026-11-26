// Client de l'API MLOps réelle (Databricks via le backend ARGOS, préfixe /api).
// Aucun secret côté navigateur : le backend détient l'authentification Databricks.
// Aucune donnée de repli : une erreur reste une erreur (jamais de valeurs inventées).

const BASE = import.meta.env.VITE_API_URL ?? '/api';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Read options: `fresh` bypasses the server cache; `signal` cancels the request. */
export interface ReadOpts { fresh?: boolean; signal?: AbortSignal; timeoutMs?: number }

/** Freshness of a response, from the backend headers (real Databricks read time). */
export interface ResponseMeta { fetchedAt: string | null; cache: 'hit' | 'miss' | 'mixed' | 'stale' | null }
const META = new WeakMap<object, ResponseMeta>();
export const metaOf = (data: unknown): ResponseMeta =>
  (data !== null && typeof data === 'object' ? META.get(data) : undefined) ?? { fetchedAt: null, cache: null };

const DEFAULT_TIMEOUT_MS = 30_000; // > backend request budget (25 s)

async function call<T>(path: string, init?: RequestInit, opts: ReadOpts = {}): Promise<T> {
  const url = BASE + path + (opts.fresh ? `${path.includes('?') ? '&' : '?'}fresh=true` : '');
  const controller = new AbortController();
  const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  opts.signal?.addEventListener('abort', onAbort);
  let res: Response;
  try {
    res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...init, signal: controller.signal });
  } catch {
    if (opts.signal?.aborted) throw new ApiError(0, 'Requête annulée');
    if (controller.signal.aborted) throw new ApiError(0, `Délai dépassé (${Math.round(timeoutMs / 1000)} s)`);
    throw new ApiError(0, 'Backend HOVIS injoignable');
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener('abort', onAbort);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      // Corps vide ou non JSON : en dev, c'est le proxy Vite qui ne joint pas le backend.
      if (res.status >= 500) detail = 'Backend HOVIS injoignable ou en erreur (aucune donnée affichée)';
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json();
  if (data !== null && typeof data === 'object') {
    const cache = res.headers.get('X-HOVIS-Cache');
    META.set(data, {
      fetchedAt: res.headers.get('X-HOVIS-Fetched-At'),
      cache: cache === 'hit' || cache === 'miss' || cache === 'mixed' || cache === 'stale' ? cache : null,
    });
  }
  return data as T;
}

/* ------------------------------------------------------------------ types (réponses réelles) */

export interface ConnectionStatus { ok: boolean; host: string; user_active: boolean; profile: string }

export interface ManagedModel {
  id: string; display_name: string; use_case: string; argos_use_case: string; scope: string;
  uc_name: string; endpoint: string | null; training_job: string | null; synthetic: boolean;
}

export interface ModelVersionInfo {
  name: string; version: string; aliases: string[]; run_id: string | null; model_id: string | null;
  source: string; status: string; tags: Record<string, string>; created_at: string | null;
}

export interface VersionStatus { version: ModelVersionInfo; approved: boolean; aliases: string[]; served_by: string[] }

export interface ModelStatus {
  model_id: string; uc_name: string; aliases: Record<string, string>;
  served: Record<string, string | null>; versions: VersionStatus[];
}

export interface RunSummary {
  run_id: string; run_name: string | null; experiment_id: string; status: string;
  start_time: string | null; end_time: string | null; params: Record<string, string>;
  metrics: Record<string, number>; tags: Record<string, string>;
}

export interface SchemaInfo { catalog: string; name: string; full_name: string; comment: string | null }

export interface ExperimentInfo { experiment_id: string; name: string; lifecycle_stage: string }

export interface JobRunInfo {
  run_id: number; job_id: number | null; life_cycle_state: string | null; result_state: string | null;
  state_message: string | null; start_time: string | null; end_time: string | null; duration_s: number | null;
}

export interface JobInfo { job_id: number; name: string; scheduled: boolean; triggerable: boolean; last_run: JobRunInfo | null }

export interface ServedEntity {
  name: string | null; model: string | null; version: string | null; workload_size: string | null;
  scale_to_zero: boolean | null; deployment: string | null;
}

export interface EndpointInfo { name: string; ready: string | null; config_update: string | null; served: ServedEntity[]; pending_versions: string[] }

export interface DriftMeasure { feature: string; method: string; value: number; threshold: number; alert: boolean }

export interface MonitoringReport {
  available: boolean; reason: string | null; table: string; read_at: string | null;
  accuracies: Record<string, number | null>;
  metrics: { model: { registered_model: string; version: string }; n_inferences: number; window_end: string; drift: DriftMeasure[] } | null;
  /** Dernière lecture réussie (persistée par le serveur), affichée comme telle. */
  last_snapshot: MonitoringReport | null;
}

export interface Comparison {
  runs: { run_id: string; run_name: string | null }[];
  metrics: Record<string, Record<string, number | null>>;
  params: Record<string, Record<string, string | null>>;
}

export interface LiveOverviewModel {
  id: string; name: string; useCase: string; scope: string; version: string;
  healthPct: number | null; recallKoPct: number | null; servedVersion: string | null;
  championVersion: string | null; approvedVersions: string[]; synthetic: boolean;
}

export interface LiveOverview {
  threshold: number;
  counts: { healthy: number; watch: number; retrain: number };
  drifts: { modelId: string; title: string; detail: string; healthPct: number | null; mode: string; stale?: boolean }[];
  models: LiveOverviewModel[];
  retrainMode: 'MANUEL' | 'AUTO';
  dataStatus: { source: string; healthPct: string; unavailable: string[] };
}

/* ------------------------------------------------------------------ appels */

const q = encodeURIComponent;

export const mlops = {
  health: (o?: ReadOpts) => call<ConnectionStatus>('/mlops/health', undefined, o),
  catalogs: (o?: ReadOpts) => call<string[]>('/mlops/catalogs', undefined, o),
  schemas: (catalog: string, o?: ReadOpts) => call<SchemaInfo[]>(`/mlops/catalogs/${q(catalog)}/schemas`, undefined, o),
  overview: (o?: ReadOpts) => call<LiveOverview>('/models/overview', undefined, o),
  models: (o?: ReadOpts) => call<ManagedModel[]>('/mlops/models', undefined, o),
  status: (id: string, o?: ReadOpts) => call<ModelStatus>(`/mlops/models/${q(id)}/status`, undefined, o),
  run: (runId: string, o?: ReadOpts) => call<RunSummary>(`/mlops/runs/${q(runId)}`, undefined, o),
  compare: (runIds: string[]) => call<Comparison>(`/mlops/runs/compare?ids=${runIds.map(q).join(',')}`),
  experiments: (o?: ReadOpts) => call<ExperimentInfo[]>('/mlops/experiments', undefined, o),
  runs: (experimentId: string, o?: ReadOpts) => call<RunSummary[]>(`/mlops/experiments/${q(experimentId)}/runs?limit=10`, undefined, o),
  jobs: (o?: ReadOpts) => call<JobInfo[]>('/mlops/jobs', undefined, o),
  jobRun: (runId: number) => call<JobRunInfo>(`/mlops/job-runs/${runId}`),
  jobRuns: (jobId: number, o?: ReadOpts) => call<JobRunInfo[]>(`/mlops/jobs/${jobId}/runs?limit=10`, undefined, o),
  endpoints: (o?: ReadOpts) => call<EndpointInfo[]>('/mlops/endpoints', undefined, o),
  // An explicit live read may wait for a running SQL warehouse: longer, still bounded.
  monitoring: (id: string, refresh = false, o?: ReadOpts) =>
    call<MonitoringReport>(`/mlops/models/${q(id)}/monitoring${refresh ? '?refresh=true' : ''}`, undefined, refresh ? { ...o, timeoutMs: 180_000 } : o),
  approve: (id: string, version: string) => call<VersionStatus>(`/mlops/models/${q(id)}/versions/${q(version)}/approve`, { method: 'POST' }),
  promote: (id: string, version: string) => call<ModelStatus>(`/models/${q(id)}/promote`, { method: 'POST', body: JSON.stringify({ version }) }),
  retrain: (id: string) => call<JobRunInfo>(`/models/${q(id)}/retrain`, { method: 'POST' }),
  setRetrainMode: (mode: 'MANUEL' | 'AUTO') => call<void>('/models/retrain-mode', { method: 'PUT', body: JSON.stringify({ mode }) }),

  // ---------------------------------------------------------------- datasets (DBX-04)
  datasets: (id: string, o?: ReadOpts) => call<DatasetIndex>(`/mlops/models/${q(id)}/datasets`, undefined, o),
  datasetItems: (id: string, version: string, f: ItemFilters, o?: ReadOpts) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
    return call<ItemPage>(`/mlops/models/${q(id)}/datasets/${q(version)}/items?${p}`, undefined, o);
  },
  datasetTables: (id: string, o?: ReadOpts) => call<TableInfo[]>(`/mlops/models/${q(id)}/dataset-tables`, undefined, o),
  trainingDataset: (id: string, o?: ReadOpts) => call<TrainingDataset>(`/mlops/models/${q(id)}/training-dataset`, undefined, o),
  createDraft: (id: string, parentVersion: string) =>
    call<Draft>(`/mlops/models/${q(id)}/dataset-drafts`, { method: 'POST', body: JSON.stringify({ parent_version: parentVersion }) }),
  draft: (id: string, draftId: string, o?: ReadOpts) => call<Draft>(`/mlops/models/${q(id)}/dataset-drafts/${q(draftId)}`, undefined, o),
  deleteDraft: (id: string, draftId: string) => call<void>(`/mlops/models/${q(id)}/dataset-drafts/${q(draftId)}`, { method: 'DELETE' }),
  updateDraftItems: (id: string, draftId: string, changes: DraftChange[]) =>
    call<Draft>(`/mlops/models/${q(id)}/dataset-drafts/${q(draftId)}/items`, { method: 'PATCH', body: JSON.stringify({ changes }) }),
  /** One multipart request; the caller sends small batches to show real progress. */
  importFiles: (id: string, draftId: string, files: File[], label: string, split: string, attested: boolean) => {
    const form = new FormData();
    files.forEach((f) => form.append('files', f, f.name));
    form.append('label', label);
    form.append('split', split);
    form.append('synthetic_attested', String(attested));
    return call<ImportResult[]>(`/mlops/models/${q(id)}/dataset-drafts/${q(draftId)}/import`, { method: 'POST', body: form, headers: {} }, { timeoutMs: 120_000 });
  },
  removeImport: (id: string, draftId: string, sha: string) =>
    call<Draft>(`/mlops/models/${q(id)}/dataset-drafts/${q(draftId)}/imports/${q(sha)}`, { method: 'DELETE' }),
  publish: (id: string, draftId: string, version: string) =>
    call<PublishJob>(`/mlops/models/${q(id)}/dataset-drafts/${q(draftId)}/publish`, { method: 'POST', body: JSON.stringify({ version }) }),
  datasetJob: (jobId: string) => call<PublishJob>(`/mlops/dataset-jobs/${q(jobId)}`),
};

/** Image URLs (served by the backend from the manifest whitelist; no credential in the browser). */
export const datasetImageUrl = (id: string, version: string, file: string) =>
  `${BASE}/mlops/models/${q(id)}/datasets/${q(version)}/images/${file.split('/').map(q).join('/')}`;
export const draftImageUrl = (id: string, draftId: string, sha: string) =>
  `${BASE}/mlops/models/${q(id)}/dataset-drafts/${q(draftId)}/images/${q(sha)}`;

/* ------------------------------------------------------------------ datasets (types) */

export interface DatasetRef {
  name: string; version: string; uri: string; manifest_sha256: string | null; num_samples: number;
  splits: Record<string, number>; split_strategy: string; confidential: boolean; classes: string[];
}
export interface DatasetVersion {
  version: string; ref: DatasetRef; uri: string; schema_version: number;
  parent_version: string | null; parent_manifest_sha256: string | null; created_at: string | null; created_by: string | null;
  use_case: string | null; annotation_format: string; classes: string[]; counts: Record<string, Record<string, number>>;
  split_strategy: string; split_fingerprints: Record<string, string>; synthetic: boolean; description: string | null;
  provenance: Record<string, unknown>; changes: Record<string, number> | null; evaluation_reference_changed: boolean | null;
  evaluation_changes: { file: string; split: string; change: string }[]; excluded_items: { file: string; sha256: string; label: string; split: string }[];
  used_by: { model_version: string; run_id: string | null }[]; locked: boolean;
}
export interface DraftSummary {
  draft_id: string; parent_version: string; status: string; created_at: string; updated_at: string;
  n_changes: number; n_imports: number; target_version: string | null; published_version: string | null;
}
export interface DatasetIndex {
  model_id: string; root: string; name: string | null; versions: DatasetVersion[];
  incomplete: { version: string; state: 'publishing' | 'interrupted'; draft_id: string | null }[]; drafts: DraftSummary[];
}
export interface DatasetItem {
  file: string; label: string; split: string; sha256: string; review?: string; previous_label?: string;
  origin?: Record<string, unknown>; label_history?: { version: string; label: string; review?: string; note?: string }[];
  [key: string]: unknown;
}
export interface ItemFilters { split?: string; label?: string; review?: string; q?: string; offset?: number; limit?: number }
export interface ItemPage { total: number; offset: number; limit: number; facets: Record<string, Record<string, number>>; items: DatasetItem[] }
export interface DraftChange { file: string; action: 'validate' | 'relabel' | 'exclude' | 'reset'; label?: string; note?: string }
export interface DraftImport {
  stored: string; sha256: string; ext: string; format: string; width: number; height: number; size: number;
  label: string; split: string; original_name: string; imported_at: string;
}
export interface Draft {
  draft_id: string; model_id: string; parent_version: string; parent_manifest_sha256: string; status: 'open' | 'publishing' | 'published';
  created_at: string; updated_at: string; changes: Record<string, { action: string; label?: string; note?: string | null }>;
  imports: DraftImport[]; target_version?: string; published_version?: string; published_manifest_sha256?: string;
}
export interface ImportResult { name: string; accepted: boolean; reason: string | null; sha256: string | null }
export interface PublishJob {
  job_id: string; model_id: string; draft_id: string; version: string; state: 'running' | 'succeeded' | 'failed';
  phase: string; done: number; total: number; error: string | null; manifest_sha256: string | null; resumed: boolean;
}
export interface TableInfo { name: string; columns: { name: string; type: string }[]; num_rows: number | null; last_commit: string | null; note: string }
export interface TrainingDataset { job_name: string | null; dataset_dir: string | null; dataset_version: string | null; source: string }
