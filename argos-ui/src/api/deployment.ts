// Dedicated lifecycle client. No UI action calls it until the Registry and Deployment mockups land.
// The backend owns Databricks credentials; declared authors are not verified identities.

const BASE = (import.meta as ImportMeta & { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL ?? '/api';
export const LIFECYCLE_READ_ONLY = (import.meta as ImportMeta & { env?: { VITE_LIFECYCLE_READ_ONLY?: string } }).env?.VITE_LIFECYCLE_READ_ONLY === 'true';

export type DecisionValue = 'approved' | 'rejected';
export type OperationStatus =
  | 'prepared' | 'requesting' | 'updating' | 'verifying'
  | 'succeeded' | 'failed' | 'uncertain' | 'expired';

export interface DecisionRequest {
  decision: DecisionValue;
  reason: string;
  author_declared: string;
  role_declared?: string;
  acknowledge_served_rejection?: boolean;
}

export interface DecisionRecord extends DecisionRequest {
  decision_id: string;
  model_id: string;
  version: string;
  authenticated_identity: null;
  served_when_decided: boolean | null;
  requires_serving_action: boolean;
  status: 'requesting' | 'applied' | 'uncertain';
  created_at: string;
  completed_at: string | null;
  error: string | null;
}

export interface PrepareDeployment {
  model_id: string;
  version: string; // numeric and immutable, never an alias
  endpoint: string;
  reason: string;
  author_declared: string;
  role_declared?: string;
}

export interface DeploymentOperation {
  operation_id: string;
  kind: 'deploy' | 'rollback';
  model_id: string;
  registered_model: string;
  version: string;
  endpoint: string;
  previous_version: string;
  previous_config: Record<string, unknown>;
  requested_config: Record<string, unknown>;
  reason: string;
  author_declared: string;
  role_declared: string;
  authenticated_identity: null;
  source_operation_id: string | null;
  status: OperationStatus;
  confirmation: string;
  created_at: string;
  updated_at: string;
  expires_at: string;
  submitted_at: string | null;
  completed_at: string | null;
  verification: Record<string, unknown> | null;
  error: string | null;
  inference_tested: false;
}

async function call<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    signal,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === 'string' ? payload.detail : `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

const registry = (modelId: string, version: string) =>
  `/mlops/registry/${encodeURIComponent(modelId)}/versions/${encodeURIComponent(version)}`;

export const deploymentApi = {
  decisionState: (modelId: string, version: string, signal?: AbortSignal) =>
    call<Record<string, unknown>>(`${registry(modelId, version)}/decision-state`, 'GET', undefined, signal),
  decisionHistory: (modelId: string, version: string, signal?: AbortSignal) =>
    call<DecisionRecord[]>(`${registry(modelId, version)}/decisions`, 'GET', undefined, signal),
  decide: (modelId: string, version: string, decision: DecisionRequest) =>
    call<DecisionRecord>(`${registry(modelId, version)}/decisions`, 'POST', decision),
  history: (endpoint?: string, signal?: AbortSignal) => call<DeploymentOperation[]>(
    `/mlops/deployments?limit=500${endpoint ? `&endpoint=${encodeURIComponent(endpoint)}` : ''}`, 'GET', undefined, signal),
  get: (id: string, signal?: AbortSignal) =>
    call<DeploymentOperation>(`/mlops/deployments/${encodeURIComponent(id)}`, 'GET', undefined, signal),
  events: (id: string, signal?: AbortSignal) => call<Array<{ at: string; status: OperationStatus; note: string | null }>>(
    `/mlops/deployments/${encodeURIComponent(id)}/events`, 'GET', undefined, signal),
  edgeStations: (signal?: AbortSignal) =>
    call<EdgeStation[]>('/v1/stations', 'GET', undefined, signal),
  prepare: (request: PrepareDeployment) =>
    call<DeploymentOperation>('/mlops/deployments/prepare', 'POST', request),
  prepareRollback: (sourceOperationId: string, reason: string, authorDeclared: string) =>
    call<DeploymentOperation>('/mlops/deployments/rollback/prepare', 'POST', {
      source_operation_id: sourceOperationId, reason, author_declared: authorDeclared,
    }),
  confirm: (id: string, confirmation: string) =>
    call<DeploymentOperation>(`/mlops/deployments/${encodeURIComponent(id)}/confirm`,
      'POST', { confirmation }),
};

export interface EdgeStation {
  station_id: string;
  name: string;
  cell: string;
  online: boolean;
  simulated: boolean;
  last_seen_at: string | null;
  models: Array<{
    use_case: string;
    status: 'loaded' | 'loading' | 'failed' | 'absent';
    model: { registered_model: string; version: string } | null;
    loaded_at: string | null;
    error: string | null;
  }>;
}
