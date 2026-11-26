/** Industrial HTTP contract. No demo fixture or Databricks request is used here. */
export const LIVE_INDUSTRIAL = import.meta.env.VITE_LIVE_INDUSTRIAL === 'true';

export type Verdict = 'OK' | 'NOK' | 'HOLD' | 'ERROR';
export type AlertStatus = 'open' | 'acknowledged' | 'validated' | 'rejected' | 'resolved';

export interface Kpi {
  total_parts: number; ok_parts: number; nok_parts: number; hold_parts: number;
  error_parts: number; predicted_nok_parts: number; corrected_parts: number;
  target_parts: number | null; expected_ok_parts_by_now: number | null;
  actual_ok_rate_per_hour: number | null; actual_total_rate_per_hour: number | null;
  efficiency: number | null; nok_rate: number | null;
}
export interface Shift {
  shift_id: string; name: string; status: 'OPEN' | 'CLOSED';
  started_at: string; ended_at: string | null; target_parts: number;
}
export interface Station {
  station_id: string; cell: string; simulated: boolean; online: boolean;
  last_seen_at: string | null; open_alerts: number;
  current_shift: { shift: Shift; kpi: Kpi } | null;
  equipment: { equipment_id: string; equipment_type: string; status: string; detail: string | null }[];
}
export interface Part {
  part_id: string; station_id: string; cycle_id: string; created_at: string;
  predicted_verdict: Verdict; effective_verdict: Verdict; correction_count: number;
  prediction: { score: number; model_name: string; model_version: string } | null;
  disposition: string;
}
export interface Alert {
  alert_id: string; station_id: string; use_case: 'quality' | 'safety' | 'workstation' | null;
  alert_type: string; severity: 'info' | 'warning' | 'critical'; status: AlertStatus;
  title: string; first_seen_at: string; last_seen_at: string; occurrences: number;
  simulated: boolean;
}
export interface EdgeEvent {
  event_id: string; station_id: string; event_type: string; occurred_at: string;
  simulated: boolean; use_case: string | null; payload: Record<string, unknown>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    });
  } catch {
    throw new Error('Service industriel injoignable');
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') detail = body.detail;
    } catch { /* The proxy may return an empty body. */ }
    throw new Error(`${response.status} · ${detail}`);
  }
  return response.json() as Promise<T>;
}

const core = '/api/v1';
const edge = '/production';
const id = encodeURIComponent;

export const industrial = {
  stations: () => request<Station[]>(`${core}/stations`),
  station: (stationId: string) => request<Station>(`${core}/stations/${id(stationId)}`),
  kpi: (stationId?: string, from?: string, to?: string) => {
    const query = new URLSearchParams();
    if (stationId) query.set('station_id', stationId);
    if (from) query.set('from', from);
    if (to) query.set('to', to);
    return request<Kpi>(`${core}/kpi?${query}`);
  },
  parts: (stationId: string, limit = 100) =>
    request<Part[]>(`${core}/parts?station_id=${id(stationId)}&limit=${limit}`),
  alerts: (stationId?: string) =>
    request<Alert[]>(`${core}/alerts${stationId ? `?station_id=${id(stationId)}` : ''}`),
  events: (stationId: string, limit = 100) =>
    request<EdgeEvent[]>(`${core}/events?station_id=${id(stationId)}&limit=${limit}`),
  edgeParts: (stationId: string) =>
    request<Part[]>(`${edge}/parts?station_id=${id(stationId)}&limit=1`),
  correct: (part: Part, newVerdict: 'OK' | 'NOK', reason: string, physicalInspection: boolean) =>
    request<Part>(`${edge}/parts/${id(part.part_id)}/corrections`, {
      method: 'POST',
      body: JSON.stringify({
        new_verdict: newVerdict,
        expected_current_verdict: part.effective_verdict,
        reason,
        actor_role: 'operator',
        physical_inspection: physicalInspection,
      }),
    }),
  alertAction: (alertId: string, action: 'acknowledge' | 'validate' | 'reject' | 'resolve') =>
    request<Alert>(`${core}/alerts/${id(alertId)}/${action}`, { method: 'POST' }),
};

export const activeAlert = (alert: Alert) =>
  alert.status === 'open' || alert.status === 'acknowledged' || alert.status === 'validated';
export const latest = (parts: Part[]) => parts[0] ?? null;
export const ratePct = (rate: number | null) => rate == null ? '—' : `${(rate * 100).toFixed(1)} %`;
export const displayVerdict = (verdict: Verdict) => verdict === 'NOK' ? 'KO' : verdict === 'HOLD' ? 'À vérifier' : verdict;
export const stationLabel = (station: Station) => `${station.station_id}${station.simulated ? ' · simulé' : ''}`;
