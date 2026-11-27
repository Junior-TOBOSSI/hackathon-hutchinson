// Client Monitoring (DBX-07B/C) : routes /api/mlops/monitoring. Les GET n'écrivent jamais ;
// seules la collecte et le gel d'une référence sont des écritures (locales, explicites).
import { call, type ReadOpts } from './mlops';

const q = encodeURIComponent;
const M = '/mlops/monitoring';

export type DataKind = 'real' | 'simulated';
export interface Filters {
  data_kind: DataKind | 'all'; granularity?: 'hour' | 'day'; use_case?: string; model_key?: string; version?: string; station?: string; start?: string; end?: string;
}
export interface SourceStatus { name: string; status: 'available' | 'unavailable' | 'partial'; fetched_at: string | null; detail: string | null }
export interface Aggregate {
  n_inferences: number; n_parts: number; cadence_per_hour: number | null; score_mean: number | null;
  score_histogram: { edges: number[]; counts: number[] };
  decision_counts: Record<string, number>; decision_rates: Record<string, number | null>;
  latency_ms: { mean: number | null; p50: number | null; p95: number | null };
  first_activity: string | null; last_activity: string | null; simulated: boolean[];
}
export interface Group extends Aggregate { model_key: string; model_version: string; station_id: string; registry_link: string }
export interface Human {
  corrected_parts: number; corrections: number; correction_types: Record<string, number>; false_rejects_observed: number;
  missed_defects_observed: number; physical_inspections: number; verified_parts: number | null; agreement_rate: number | null;
  agreement_status: string; warning: string; items: CorrectionItem[];
}
export interface CorrectionItem {
  correction_id: string; at: string; station_id: string; part_id: string; sequence: number; model_key: string | null; model_version: string | null;
  ai_initial: string | null; previous_verdict: string | null; new_verdict: string; reason: string | null; physical_inspection: boolean;
  actor_role: string | null; simulated: boolean;
}
export interface Operational {
  status: 'available' | 'unavailable' | 'partial'; sources: SourceStatus[]; data_kind: string; total: Aggregate; groups: Group[];
  parts: { n_parts: number; with_inference_error: number; error_codes: Record<string, number>; note: string };
  model_states: { station_id: string; cell: string | null; simulated: boolean; online: boolean; last_seen_at: string | null; equipment: { equipment_id: string; status: string }[] }[];
  human: Human;
  by_model_version: (Aggregate & { model_key: string; model_version: string })[];
  series: { granularity: 'hour' | 'day'; source: string; points: SeriesPoint[] } | null;
}
export interface SeriesPoint { bucket_start: string; n_inferences: number; latency_p50: number | null; latency_p95: number | null; decision_counts: Record<string, number> }
export type DriftStatus = 'alert' | 'watch' | 'stable' | 'reference_absent' | 'insufficient_reference' | 'insufficient_current'
  | 'incompatible' | 'mixed_data' | 'no_production_data' | 'available';
export interface CatalogRow {
  model_key: string; source: 'operational' | 'registry'; name: string; use_case: string | null; registry_link: string; model_id?: string;
  versions: string[]; stations: string[]; n_inferences: number; n_parts: number; latency_p95: number | null; last_activity: string | null;
  simulated: boolean[]; corrections: number; synthetic?: boolean; note?: string;
  drift: { status: DriftStatus; version?: string; reasons?: string[]; reference_id?: string; n_reference?: number; n_current?: number; reason?: string };
  open_alerts: number; references: number; needs_investigation: boolean;
}
export interface Reference {
  reference_id: string; source: 'offline_test' | 'operational_window'; model_key: string; model_version: string; run_id: string | null;
  window: { start: string; end: string } | null; created_at: string; n: number; edges: (number | null)[] | null;
  decision_counts: Record<string, number>; representative: boolean; warnings: string[]; score_definition: string;
  synthetic: boolean | null; fingerprints: Record<string, string | null>;
}
export interface ModelDetail extends Omit<CatalogRow, 'references'> { references: Reference[]; alerts: Alert[] }
export interface Measure { indicator: string; method: string; value?: number | null; threshold?: number; level?: string; statistic?: number; p_value?: number; applicable?: boolean; reason?: string; dof?: number; method_detail?: string }
export interface Thresholds { psi_watch: number; psi_alert: number; min_reference: number; min_current: number; latency_shift_ratio: number }
export interface DriftResult {
  status: DriftStatus; reasons?: string[]; detail?: string; reference_id?: string; reference_source?: string; reference_representative?: boolean;
  reference_warnings?: string[]; n_reference?: number; n_current?: number; thresholds?: Thresholds;
  histogram?: { edges: (number | null)[]; reference: number[]; current: number[] | null; reference_counts: number[]; current_counts: number[] } | null;
  measures?: Measure[]; note?: string; core_status?: string;
}
export interface Alert {
  alert_key: string; model_key: string; state: 'open' | 'resolved'; first_detected: string; last_detected: string; resolved_at: string | null;
  kind: 'drift' | 'availability'; indicator: string; method?: string; value: number | string | null; threshold?: number; n?: number;
  reference_id?: string; scope?: string; data_kind?: string; station_id?: string; model_version?: string; window_day?: string;
}
export interface Snapshot extends Aggregate { snapshot_id: string; scope_key: string; window_start: string; window_end: string; data_kind: DataKind; computed_at: string; partial: boolean }
export interface Collection { collection_id: string; at: string; snapshots_written: number; open_alerts: number; resolved_alerts: number; partial: boolean; inferences: number; sources: SourceStatus[] }
export interface Summary {
  status: string; sources: SourceStatus[]; data_kind: string; models_monitored: number; stations: number; stations_online: number;
  inferences: number; parts: number; open_alerts: number; drift_alerts: number; availability_alerts: number; last_collection: string | null;
  simulated_only: boolean; latency_p95: number | null;
}
export interface PerfVersion {
  version: string; run_id: string; approved: boolean; aliases: string[]; dataset: { id: string | null; version: string | null; test_fingerprint: string | null };
  metrics: Record<string, number | null>; per_class: Record<string, { support: number; precision: number | null; recall: number | null; f1: number | null }> | null;
  confusion: { columns: string[]; matrix: Record<string, Record<string, number>> } | null; synthetic: boolean; representative: boolean | null; warnings: string[];
}
export interface Performance { model_id: string; scope: string; versions: PerfVersion[]; comparable_groups: string[][] }
export interface Signals {
  model_id: string; eligible: boolean; action: string;
  conditions: Record<string, { met?: boolean; status?: string; threshold?: number | null; note?: string; [k: string]: unknown }>;
}

const qs = (f: Partial<Filters> & Record<string, string | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v) p.set(k, v);
  return p.toString();
};

export const monitoring = {
  summary: (kind: string, o?: ReadOpts) => call<Summary>(`${M}/summary?data_kind=${kind}`, undefined, o),
  models: (f: Filters, o?: ReadOpts) => call<CatalogRow[]>(`${M}/models?${qs({ ...f, model_key: undefined, version: undefined, granularity: undefined })}`, undefined, o),
  model: (key: string, kind: string, o?: ReadOpts) => call<ModelDetail>(`${M}/models/${q(key)}?data_kind=${kind}`, undefined, o),
  inferences: (f: Filters, o?: ReadOpts) => call<Operational>(`${M}/inferences?${qs({ ...f })}`, undefined, o),
  human: (f: Filters, o?: ReadOpts) => call<Operational['human'] & { status: string; sources: SourceStatus[] }>(`${M}/human?${qs({ ...f, granularity: undefined })}`, undefined, o),
  performance: (modelId: string, o?: ReadOpts) => call<Performance>(`${M}/performance/${q(modelId)}`, undefined, o),
  drift: (p: { model_key: string; version: string; data_kind: DataKind; reference_id?: string }, o?: ReadOpts) =>
    call<DriftResult>(`${M}/drift?${qs(p)}`, undefined, o),
  alerts: (o?: ReadOpts) => call<Alert[]>(`${M}/alerts`, undefined, o),
  history: (kind: DataKind, o?: ReadOpts) => call<{ snapshots: Snapshot[]; collections: Collection[] }>(`${M}/history?data_kind=${kind}`, undefined, o),
  references: (key: string, o?: ReadOpts) => call<Reference[]>(`${M}/references?model_key=${q(key)}`, undefined, o),
  signals: (modelId: string, o?: ReadOpts) => call<Signals>(`${M}/retraining-signals/${q(modelId)}`, undefined, o),
  freeze: (body: { source: 'operational_window'; model_key: string; version: string; start: string; end: string; data_kind: DataKind }) =>
    call<Reference>(`${M}/references`, { method: 'POST', body: JSON.stringify(body) }),
  collect: () => call<Collection & { collected_at: string }>(`${M}/collect`, { method: 'POST' }, { timeoutMs: 60_000 }),
};
