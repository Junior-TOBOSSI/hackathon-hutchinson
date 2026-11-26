// Client de l'API MLOps réelle (Databricks via le backend ARGOS, préfixe /api).
// Aucun secret côté navigateur : le backend détient l'authentification Databricks.
// Aucune donnée de repli : une erreur reste une erreur (jamais de valeurs inventées).

const BASE = import.meta.env.VITE_API_URL ?? '/api';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, { headers: { 'Content-Type': 'application/json' }, ...init });
  } catch {
    throw new ApiError(0, 'Backend ARGOS injoignable');
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      // Corps vide ou non JSON : en dev, c'est le proxy Vite qui ne joint pas le backend.
      if (res.status >= 500) detail = 'Backend ARGOS injoignable ou en erreur (aucune donnée affichée)';
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
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
  health: () => call<ConnectionStatus>('/mlops/health'),
  catalogs: () => call<string[]>('/mlops/catalogs'),
  schemas: (catalog: string) => call<SchemaInfo[]>(`/mlops/catalogs/${q(catalog)}/schemas`),
  overview: () => call<LiveOverview>('/models/overview'),
  models: () => call<ManagedModel[]>('/mlops/models'),
  status: (id: string) => call<ModelStatus>(`/mlops/models/${q(id)}/status`),
  run: (runId: string) => call<RunSummary>(`/mlops/runs/${q(runId)}`),
  compare: (runIds: string[]) => call<Comparison>(`/mlops/runs/compare?ids=${runIds.map(q).join(',')}`),
  experiments: () => call<ExperimentInfo[]>('/mlops/experiments'),
  runs: (experimentId: string) => call<RunSummary[]>(`/mlops/experiments/${q(experimentId)}/runs?limit=10`),
  jobs: () => call<JobInfo[]>('/mlops/jobs'),
  jobRun: (runId: number) => call<JobRunInfo>(`/mlops/job-runs/${runId}`),
  jobRuns: (jobId: number, limit = 10) => call<JobRunInfo[]>(`/mlops/jobs/${jobId}/runs?limit=${limit}`),
  endpoints: () => call<EndpointInfo[]>('/mlops/endpoints'),
  monitoring: (id: string, refresh = false) => call<MonitoringReport>(`/mlops/models/${q(id)}/monitoring${refresh ? '?refresh=true' : ''}`),
  approve: (id: string, version: string) => call<VersionStatus>(`/mlops/models/${q(id)}/versions/${q(version)}/approve`, { method: 'POST' }),
  promote: (id: string, version: string) => call<ModelStatus>(`/models/${q(id)}/promote`, { method: 'POST', body: JSON.stringify({ version }) }),
  retrain: (id: string) => call<JobRunInfo>(`/models/${q(id)}/retrain`, { method: 'POST' }),
  setRetrainMode: (mode: 'MANUEL' | 'AUTO') => call<void>('/models/retrain-mode', { method: 'PUT', body: JSON.stringify({ mode }) }),
};
