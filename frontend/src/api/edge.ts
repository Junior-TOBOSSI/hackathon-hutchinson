import { query, request } from "./http";
import type {
  Correction,
  CorrectionIn,
  DispositionIn,
  InferenceEvent,
  OperatorReportPayload,
  Part,
  PartVerdict,
  ProductionKPI,
  Shift,
  ShiftReport,
  ShiftStart,
  Stats,
  UseCaseInfo,
} from "./types";

/** Local Edge API of one station. All endpoints exist except those marked TO DEVELOP. */
export const edgeApi = {
  health: () => request<Record<string, unknown>>("edge", "/health"),
  useCases: () => request<UseCaseInfo[]>("edge", "/use-cases"),
  events: (params: { use_case?: string; decision?: string; limit?: number } = {}) =>
    request<InferenceEvent[]>("edge", `/events${query(params)}`),
  stats: () => request<Stats>("edge", "/stats"),

  parts: (params: { station_id?: string; shift_id?: string; verdict?: PartVerdict; limit?: number } = {}) =>
    request<Part[]>("edge", `/production/parts${query(params)}`),
  part: (partId: string) => request<Part>("edge", `/production/parts/${partId}`),
  corrections: (partId: string) => request<Correction[]>("edge", `/production/parts/${partId}/corrections`),
  correctPart: (partId: string, body: CorrectionIn) =>
    request<Part>("edge", `/production/parts/${partId}/corrections`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  setDisposition: (partId: string, body: DispositionIn) =>
    request<Part>("edge", `/production/parts/${partId}/disposition`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  currentShift: (stationId: string) =>
    request<ShiftReport>("edge", `/production/stations/${stationId}/shifts/current`),
  startShift: (stationId: string, body: ShiftStart) =>
    request<Shift>("edge", `/production/stations/${stationId}/shifts`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  closeShift: (shiftId: string) => request<ShiftReport>("edge", `/production/shifts/${shiftId}/close`, { method: "POST" }),
  stationKpi: (stationId: string, params: { from?: string; to?: string } = {}) =>
    request<ProductionKPI>("edge", `/production/stations/${stationId}/kpi${query(params)}`),

  /** TO DEVELOP (Edge): operator report to the supervisor, forwarded to Core via the outbox. */
  reportProblem: (stationId: string, body: Omit<OperatorReportPayload, "kind">) =>
    request<OperatorReportPayload>("edge", `/production/stations/${stationId}/reports`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
