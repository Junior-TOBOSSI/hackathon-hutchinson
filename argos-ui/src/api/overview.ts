// Client de la page d'accueil AI Leader (DBX-09) : /api/mlops/overview/v2/{bloc}.
// Chaque bloc est chargé indépendamment ; aucune route n'écrit ni ne lance quoi que ce soit.
import { call, type ReadOpts } from './mlops';

export type BlockName = 'datasets' | 'training' | 'registry' | 'infrastructure' | 'monitoring' | 'retraining' | 'activity';
export interface Block<T> {
  name: BlockName; status: 'available' | 'partial' | 'unavailable' | 'simulated'; fetched_at: string;
  data?: T; detail?: string; failed: { source: string; detail: string }[];
}

export interface DatasetsData {
  expected: { dataset_id: string; use_case: string; pipelines: string[] }[];
  families: number; published_versions: number; latest_images: number | null; drafts: number; by_use_case: Record<string, number>;
  items: { dataset_id: string; name: string; use_case: string; synthetic: boolean; versions: number; latest_version: string | null; latest_images: number | null }[];
}
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown';
export interface TrainingData {
  by_status: Partial<Record<RunStatus, number>>; running: number; scope: string;
  kpis: { candidates?: number; versions_produced?: number; trainings_30d?: number; succeeded?: number; failed?: number };
  pipelines: { pipeline_id: string; name: string; use_case: string; executable: boolean }[];
  runs: { job_run_id: number; pipeline_id: string; dataset_id: string | null; dataset_version: string | null; status: RunStatus; started_at: string | null; ended_at: string | null; duration_s: number | null; model_versions: string[] }[];
}
export interface RegistryVersion { version: string; created_at: string | null; approved: boolean; rejected: boolean; aliases: string[]; served_by: string[]; candidate: boolean }
export interface RegistryData {
  models: {
    model_id: string; name: string; use_case: string; uc_name: string; synthetic: boolean; versions: RegistryVersion[];
    candidates: number; approved: number; champion: string | null; served: Record<string, string>;
    edge_declared: { station_id: string; simulated: boolean; model_name?: string; model_version?: string; package_sha256?: string | null }[];
  }[];
  by_use_case: Record<string, number>; versions: number; candidates: number; approved: number; champions: number; served_endpoints: number; edge_note: string;
}
export interface InfrastructureData {
  checks: { name: 'databricks' | 'mlflow' | 'unity_catalog'; status: 'available' | 'unavailable'; detail: unknown }[];
  endpoints: { name: string; ready: string | null; served: [string, string][] }[];
  core: { status: string; detail: string | null; fetched_at: string | null };
  fleet: { stations: number; online: number; offline: number; simulated: number; cells: number };
  monitoring_coverage: { operational_models: number; with_representative_reference: number; registry_models_without_inference: number };
}
export interface MonitoringData {
  data_kind: 'real' | 'simulated'; core_status: string; inferences: number; latency_p95: number | null; open_alerts: number;
  drift_alerts: number; availability_alerts: number; last_collection: string | null; drift_states: Record<string, number>;
  drift_detected: number; reference_absent: number; insufficient_coverage: number; to_investigate: number; note: string;
}
export interface RetrainingData {
  active: number; inactive: number; automatic: number; pending_proposals: number; uncertain_proposals: number;
  satisfied_conditions: number; eligible_policies: number; automatic_launches: number;
  scheduler: { enabled: boolean; running?: boolean; last_tick?: string | null };
  remote_lock: { remote_launch_enabled: boolean; variable: string };
  policies: { policy_id: string; name: string; model_id: string; active: boolean; mode: 'manual' | 'auto'; version: number }[];
}
export interface ActivityEvent {
  at: string; type: string; source: string; title: string; detail: string | null; status: string;
  link: Record<string, string> | null;
}
export interface ActivityData { events: ActivityEvent[]; total: number; not_dated: string[] }

export const overview = {
  block: <T,>(name: BlockName, o?: ReadOpts) => call<Block<T>>(`/mlops/overview/v2/${name}`, undefined, o),
};
