// Client Training Factory (DBX-05) : routes /api/mlops/training. Aucun secret côté navigateur.
import { call, type DatasetFamilySummary, type ReadOpts } from './mlops';

const q = encodeURIComponent;
const T = '/mlops/training';

export interface ParamSpec { name: string; type: 'int' | 'float' | 'bool' | 'str'; default: unknown; min: number | null; max: number | null; level: 'basic' | 'advanced' | 'imposed'; label: string; help: string | null; choices: string[] }
export interface PipelineSpec {
  id: string; name: string; use_case: string; task: string; architecture: string; description: string;
  code: Record<string, string>; classes: string[];
  dataset: { families: string[]; annotation_format: string; image_extensions: string[]; required_splits: string[]; group_field: string | null; group_required: boolean };
  parameters: ParamSpec[]; compute: Record<string, unknown>; job: Record<string, unknown>; entrypoints: Record<string, string>;
  outputs: string[]; mlflow: Record<string, string>; evaluation: Record<string, unknown>;
}
export interface PipelineView { spec: PipelineSpec; executable: boolean; requirements: { id: string; label: string; ok: boolean; detail: string | null }[] }
export interface CompatibleDataset { family: DatasetFamilySummary; declared: boolean; classes_match: boolean }
export interface DatasetPreview {
  dataset_id: string; version: string; manifest_sha256: string; num_images: number; classes: string[];
  class_counts: Record<string, number>; split_counts: Record<string, number>; split_strategy: string; annotation_format: string;
  synthetic: boolean; provenance: Record<string, unknown>; groups: number | null; split_fingerprints: Record<string, string>;
}
export interface Check { id: string; label: string; status: 'ok' | 'warning' | 'error'; detail: string | null }
export interface ValidationReport {
  pipeline_id: string; dataset: DatasetPreview | null; parameters: Record<string, unknown>; checks: Check[]; launchable: boolean;
  compute: Record<string, unknown>; mlflow: Record<string, string>; code: Record<string, string>; command_preview: string[];
}
export interface LaunchRecord { request_id: string; idempotency_key: string; status: 'submitted' | 'uncertain' | 'refused'; job_run_id: number | null; error: string | null }
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown';
export interface TrainingRow {
  id: string; job_run_id: number; pipeline_id: string; pipeline_name: string; dataset_id: string | null; dataset_version: string | null;
  status: RunStatus; started_at: string | null; ended_at: string | null; duration_s: number | null; mlflow_runs: string[];
  model_versions: string[]; registered_model: string; run_page_url: string | null;
}
export interface Kpis {
  trainings_30d: number; succeeded: number; running: number; failed: number; pipelines_total: number; pipelines_executable: number;
  candidates: number; versions_produced: number; last_training_at: string | null; last_training_label: string | null;
}
export interface MlRun { run_id: string; run_name: string | null; status: string; start_time: string | null; end_time: string | null; metrics: Record<string, number>; params: Record<string, string>; tags: Record<string, string> }
export interface RunDetail { row: TrainingRow; pipeline: PipelineSpec; runs: MlRun[] }
export interface Point { key: string; value: number; step: number; timestamp: string }
export interface Evaluation {
  available: boolean; kind?: 'workstation'; reason?: string; split?: string; metrics?: Record<string, unknown>; truth_classes?: string[]; columns?: string[];
  matrix?: Record<string, Record<string, number>>; per_class?: Record<string, { support: number; precision: number | null; recall: number | null; f1: number | null }>; n?: number;
}
export interface Prediction {
  fichier: string; vraie_classe: string; verdict: string; type_defaut: string; decision: string; score_nok: number | null; latence_ms: number | null;
  correct: boolean; false_reject: boolean; missed_defect: boolean; type_confusion: boolean; to_check: boolean; manifest_file: string | null;
  annotated_path?: string; right_reason?: boolean; alignment_failed?: boolean; found?: string; view?: string;
}
export interface PredictionPage { available: boolean; kind?: 'workstation'; total: number; offset?: number; limit?: number; items: Prediction[]; dataset_id?: string | null; version?: string | null }

export const training = {
  pipelines: (o?: ReadOpts) => call<PipelineView[]>(`${T}/pipelines`, undefined, o),
  datasets: (pipelineId: string, o?: ReadOpts) => call<CompatibleDataset[]>(`${T}/pipelines/${q(pipelineId)}/datasets`, undefined, o),
  preview: (datasetId: string, version: string, o?: ReadOpts) => call<DatasetPreview>(`${T}/datasets/${q(datasetId)}/versions/${q(version)}/preview`, undefined, o),
  validate: (body: { pipeline_id: string; dataset_id: string; version: string; parameters: Record<string, unknown> }) =>
    call<ValidationReport>(`${T}/validate`, { method: 'POST', body: JSON.stringify(body) }),
  launch: (body: { pipeline_id: string; dataset_id: string; version: string; parameters: Record<string, unknown>; idempotency_key: string }) =>
    call<LaunchRecord>(`${T}/launch`, { method: 'POST', body: JSON.stringify(body) }, { timeoutMs: 60_000 }),
  summary: (o?: ReadOpts) => call<Kpis>(`${T}/summary`, undefined, o),
  runs: (o?: ReadOpts) => call<TrainingRow[]>(`${T}/runs`, undefined, o),
  run: (id: number, o?: ReadOpts) => call<RunDetail>(`${T}/runs/${id}`, undefined, o),
  cancel: (id: number) => call<{ status: string }>(`${T}/runs/${id}/cancel`, { method: 'POST' }),
  logs: (id: number, o?: ReadOpts) => call<{ run_page_url: string | null; state: string | null; tasks: { task: string; error: string | null; logs: string | null }[] }>(`${T}/runs/${id}/logs`, undefined, o),
  history: (runId: string, o?: ReadOpts) => call<Record<string, Point[]>>(`${T}/mlflow-runs/${q(runId)}/history`, undefined, o),
  evaluation: (runId: string, o?: ReadOpts) => call<Evaluation>(`${T}/mlflow-runs/${q(runId)}/evaluation`, undefined, o),
  predictions: (runId: string, f: Record<string, string | number | undefined>, o?: ReadOpts) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v !== undefined && v !== '') p.set(k, String(v));
    return call<PredictionPage>(`${T}/mlflow-runs/${q(runId)}/predictions?${p}`, undefined, o);
  },
  artifacts: (runId: string, o?: ReadOpts) => call<{ path: string; size: number | null }[]>(`${T}/mlflow-runs/${q(runId)}/artifacts`, undefined, o),
};

export const artifactUrl = (runId: string, path: string) => `/api${T}/mlflow-runs/${q(runId)}/artifact?path=${q(path)}`;
