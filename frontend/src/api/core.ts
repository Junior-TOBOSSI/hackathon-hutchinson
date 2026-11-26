import { query, request } from "./http";
import type {
  Alert,
  ModelDeployment,
  ModelPackage,
  MonitoringMetrics,
  OperatorReport,
  RetrainingPolicy,
  StationSummary,
  TrainingJob,
} from "./types";

/** ARGOS Core API. TO DEVELOP: served by the mock mode until Core exists. */
export const coreApi = {
  stations: () => request<StationSummary[]>("core", "/api/v1/stations"),
  station: (stationId: string) => request<StationSummary>("core", `/api/v1/stations/${stationId}`),
  alerts: (params: { status?: Alert["status"]; station_id?: string } = {}) =>
    request<Alert[]>("core", `/api/v1/alerts${query(params)}`),
  updateAlert: (alertId: string, action: "acknowledge" | "validate" | "reject" | "resolve") =>
    request<Alert>("core", `/api/v1/alerts/${alertId}/${action}`, { method: "POST" }),
  operatorReports: () => request<OperatorReport[]>("core", "/api/v1/operator-reports"),

  models: () => request<ModelPackage[]>("core", "/api/v1/models"),
  deployments: () => request<ModelDeployment[]>("core", "/api/v1/deployments"),
  approveDeployment: (deploymentId: string) =>
    request<ModelDeployment>("core", `/api/v1/deployments/${deploymentId}/approve`, { method: "POST" }),
  rollbackDeployment: (deploymentId: string) =>
    request<ModelDeployment>("core", `/api/v1/deployments/${deploymentId}/rollback`, { method: "POST" }),
  monitoring: (params: { use_case?: string; station_id?: string } = {}) =>
    request<MonitoringMetrics[]>("core", `/api/v1/monitoring${query(params)}`),
  trainingJobs: () => request<TrainingJob[]>("core", "/api/v1/training-jobs"),
  retrainingPolicies: () => request<RetrainingPolicy[]>("core", "/api/v1/retraining-policies"),
};
