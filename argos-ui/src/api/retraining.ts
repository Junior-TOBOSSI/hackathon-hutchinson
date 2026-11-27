// Client des politiques de réentraînement (DBX-08) : routes /api/mlops/retraining.
// Le lancement passe toujours par TrainingService.launch côté serveur (verrou, contrôles).
import { call, type ReadOpts } from './mlops';

const q = encodeURIComponent;
const R = '/mlops/retraining';

export type ConditionKind = 'drift' | 'annotations' | 'performance' | 'schedule' | 'manual';
export type ConditionState = 'satisfied' | 'not_satisfied' | 'unavailable';
export interface Condition {
  kind: ConditionKind; enabled: boolean; required: boolean;
  drift: { min_windows: number; min_level: 'alert' | 'watch'; allowed_origins: ('real' | 'simulated')[] };
  annotations: { min_new: number };
  performance: { metric: string; max_drop: number };
  schedule: { interval_days: number };
}
export interface Guardrails { max_runs_per_month: number; min_hours_between: number; allowed_hours: [number, number] | null; cpu_only: true; allow_concurrent: false }
export interface PolicyInput {
  name: string; use_case: string; model_id: string; pipeline_id: string; dataset_family: string;
  dataset_selection: { strategy: 'latest_published' | 'pinned'; pinned_version: string | null };
  active: boolean; mode: 'manual' | 'auto'; logic: 'AND' | 'OR'; conditions: Condition[]; guardrails: Guardrails; comment: string | null;
}
export interface Policy extends PolicyInput { policy_id: string; version: number; code_version: string; created_at: string; author: string }
export interface ConditionResult { kind: ConditionKind; required: boolean; state: ConditionState; reason: string; evidence: Record<string, unknown>; simulated: boolean }
export interface GuardResult { name: string; ok: boolean; detail: string }
export interface Evaluation {
  evaluation_id: string; policy_id: string; policy_version: number; at: string; trigger: string; logic: string;
  conditions: ConditionResult[]; eligible: boolean; reason: string; target_dataset_version: string | null; guards: GuardResult[]; proposal_id: string | null;
}
export type ProposalStatus = 'pending' | 'accepted' | 'launching' | 'launched' | 'uncertain' | 'rejected';
export interface Proposal {
  proposal_id: string; policy_id: string; policy_version: number; status: ProposalStatus; created_at: string; updated_at: string;
  mode: 'manual' | 'auto'; model_id: string; pipeline_id: string; dataset_family: string; dataset_version: string;
  reasons: string[]; conditions: ConditionResult[]; simulated: boolean; decided_by: string | null; decision_note: string | null;
  idempotency_key: string | null; job_run_id: number | null; last_error: string | null;
}
export interface Scheduler { enabled: boolean; running: boolean; variable: string; interval_s: number; last_tick: string | null; last_result: unknown }
export interface RetrainKpis {
  policies: number; active: number; auto: number; pending_proposals: number; uncertain_proposals: number; launched_this_month: number;
  scheduler: Scheduler; remote_launch_enabled: boolean;
}
export interface ModelOption { model_id: string; name: string; use_case: string; uc_name: string; pipelines: { pipeline_id: string; name: string; code_version: string | null; families: string[] }[] }
export interface AuditEntry { id: number; at: string; policy_id: string | null; actor: string; event: string; [k: string]: unknown }

const post = <T,>(path: string, body?: unknown) => call<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });

export const retraining = {
  kpis: (o?: ReadOpts) => call<RetrainKpis>(`${R}/kpis`, undefined, o),
  options: (o?: ReadOpts) => call<ModelOption[]>(`${R}/options`, undefined, o),
  policies: (o?: ReadOpts) => call<Policy[]>(`${R}/policies`, undefined, o),
  policy: (id: string, o?: ReadOpts) => call<{ current: Policy; history: Policy[]; manual_requests: { request_id: string; at: string; actor: string; note: string | null }[] }>(`${R}/policies/${q(id)}`, undefined, o),
  create: (body: PolicyInput) => post<Policy>(`${R}/policies`, body),
  update: (id: string, body: PolicyInput) => call<Policy>(`${R}/policies/${q(id)}`, { method: 'PUT', body: JSON.stringify(body) }),
  activate: (id: string, on: boolean) => post<Policy>(`${R}/policies/${q(id)}/${on ? 'activate' : 'deactivate'}`),
  manual: (id: string, note: string | null) => post<{ request_id: string }>(`${R}/policies/${q(id)}/manual-request`, { note }),
  evaluate: (id: string) => post<Evaluation>(`${R}/policies/${q(id)}/evaluate`),
  evaluations: (id: string, o?: ReadOpts) => call<Evaluation[]>(`${R}/evaluations?policy_id=${q(id)}&limit=20`, undefined, o),
  proposals: (o?: ReadOpts) => call<Proposal[]>(`${R}/proposals`, undefined, o),
  accept: (id: string, note: string | null) => post<Proposal>(`${R}/proposals/${q(id)}/accept`, { note }),
  reject: (id: string, note: string | null) => post<Proposal>(`${R}/proposals/${q(id)}/reject`, { note }),
  reconcile: (id: string) => post<Proposal>(`${R}/proposals/${q(id)}/reconcile`),
  audit: (id: string | null, o?: ReadOpts) => call<AuditEntry[]>(`${R}/audit${id ? `?policy_id=${q(id)}` : ''}`, undefined, o),
  ledger: (o?: ReadOpts) => call<{ ledger_id: string; policy_id: string; proposal_id: string; at: string; status: string; job_run_id: number | null }[]>(`${R}/ledger`, undefined, o),
};

export const defaultCondition = (kind: ConditionKind): Condition => ({
  kind, enabled: false, required: false,
  drift: { min_windows: 2, min_level: 'alert', allowed_origins: ['real'] },
  annotations: { min_new: 50 }, performance: { metric: 'recall_nok', max_drop: 0.05 }, schedule: { interval_days: 30 },
});
