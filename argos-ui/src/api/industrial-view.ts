/** Adapters from industrial contracts to the existing HOVIS page components. */
import type { Alert as MockAlert, AlertCategory, HourlyCount, StationIssue, StationLive, StationStatus, WorkshopOverview } from './types';
import { activeAlert, industrial, type Alert, type Kpi, type Part, type Station } from './industrial';

export type OperatorView = Omit<StationLive, 'product' | 'shift' | 'part' | 'counters' | 'objective' | 'hourly' | 'checks' | 'qualityModelVersion' | 'partCameraOnline'> & {
  product: string | null;
  shift: { code: string; start: string; end: string } | null;
  part: { number: number | null; verdict: 'OK' | 'KO' | 'A_VERIFIER'; jointsDetected: number | null; score: number | null; imageUrl: string | null; takenAt: string } | null;
  counters: { good: number | null; ko: number | null };
  objective: { shiftTarget: number | null; expectedNow: number | null; perHour: number | null };
  hourly: HourlyCount[] | null;
  checks: { securite: boolean | null; poste: boolean | null; qualite: boolean | null; koRatePct: number | null };
  qualityModelVersion: string | null;
  partCameraOnline: boolean | null;
  industrialPart?: Part | null;
  predictedVerdict?: string;
  effectiveVerdict?: string;
  live?: boolean;
  online?: boolean;
  shiftWindow?: { startedAt: string; plannedEndAt: string; endedAt: string | null; status: 'OPEN' | 'CLOSED'; target: number; actualGood: number; now?: string } | null;
};

export const active = (alerts: Alert[]) => alerts.filter(activeAlert);
export const clockTime = (date: string) => new Date(date).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
export const pct = (value: number | null | undefined) => value == null ? 'Données indisponibles' : `${(value * 100).toFixed(1)} %`;
export const count = (value: number | null | undefined) => value == null ? '—' : value.toLocaleString('fr-FR');

export function hourly(parts: Part[], complete: boolean, start: Date, end = new Date()): HourlyCount[] | null {
  if (!complete) return null;
  const buckets = new Map<number, number>();
  for (const part of parts) {
    const at = new Date(part.created_at);
    if (at >= start && at <= end && part.effective_verdict === 'OK') {
      const key = new Date(at.getFullYear(), at.getMonth(), at.getDate(), at.getHours()).getTime();
      buckets.set(key, (buckets.get(key) ?? 0) + 1);
    }
  }
  const result: HourlyCount[] = [];
  const first = new Date(start.getFullYear(), start.getMonth(), start.getDate(), start.getHours());
  for (let at = first.getTime(); at <= end.getTime(); at += 3600000) {
    result.push({ hour: new Date(at).getHours(), good: buckets.get(at) ?? 0 });
  }
  return result.slice(-8);
}

export function issueOf(alert: Alert): StationIssue {
  const category = alert.use_case === 'safety'
    ? alert.alert_type.startsWith('behavior.') ? 'COMPORTEMENT' : 'SECURITE_EPI'
    : alert.use_case === 'workstation' ? 'POSTE'
    : alert.use_case === 'quality' ? 'QUALITE' : 'EQUIPEMENT';
  return { id: alert.alert_id, category, label: `${alert.title}${alert.simulated ? ' · observation synthétique' : ''}`, instruction: alert.title, since: alert.first_seen_at };
}

export async function operatorView(stationId: string): Promise<OperatorView> {
  const [station, edgeParts, alerts, kpi] = await Promise.all([
    industrial.station(stationId), industrial.edgeParts(stationId), industrial.alerts(stationId),
    industrial.kpi(stationId),
  ]);
  const part = edgeParts[0] ?? null;
  let shift = station.current_shift;
  if (!shift) {
    const [last] = await industrial.edgeShifts(stationId);
    if (last) shift = await industrial.edgeShiftReport(last.shift_id);
  }
  const demoClock = shift?.shift.name.startsWith('DEMO-')
    ? await industrial.demoShiftClock(shift.shift.name)
    : null;
  const demoExpected = shift && demoClock
    ? shift.shift.target_parts * Math.max(0, Math.min(1,
      (new Date(demoClock.now).getTime() - new Date(shift.shift.started_at).getTime()) /
      (new Date(shift.shift.planned_end_at).getTime() - new Date(shift.shift.started_at).getTime())))
    : null;
  const camera = station.equipment.find((item) => item.equipment_type === 'camera');
  const problems = active(alerts);
  return {
    live: true, stationId, product: null,
    shift: shift ? { code: shift.shift.name, start: clockTime(shift.shift.started_at), end: shift.shift.ended_at ? clockTime(shift.shift.ended_at) : 'en cours' } : null,
    now: new Date().toISOString(),
    part: part ? { number: null, verdict: part.effective_verdict === 'NOK' ? 'KO' : part.effective_verdict === 'OK' ? 'OK' : 'A_VERIFIER', jointsDetected: null, score: part.prediction?.score ?? null, imageUrl: null, takenAt: part.created_at } : null,
    counters: { good: shift?.kpi.ok_parts ?? kpi.ok_parts, ko: shift?.kpi.nok_parts ?? kpi.nok_parts },
    objective: { shiftTarget: shift?.kpi.target_parts ?? null, expectedNow: demoExpected ?? shift?.kpi.expected_ok_parts_by_now ?? null, perHour: shift && shift.shift.target_parts > 0 ? shift.shift.target_parts / (shift.shift.planned_duration_min / 60) : null },
    hourly: null,
    issues: problems.map(issueOf),
    checks: { securite: problems.some((item) => item.use_case === 'safety') ? false : null, poste: problems.some((item) => item.use_case === 'workstation') ? false : null, qualite: part ? part.effective_verdict === 'OK' : null, koRatePct: kpi.nok_rate == null ? null : kpi.nok_rate * 100 },
    qualityModelVersion: part?.prediction?.model_version ?? null,
    partCameraOnline: camera ? camera.status === 'ok' : null,
    industrialPart: part, predictedVerdict: part?.predicted_verdict, effectiveVerdict: part?.effective_verdict,
    online: station.online,
    shiftWindow: shift ? { startedAt: shift.shift.started_at, plannedEndAt: shift.shift.planned_end_at, endedAt: shift.shift.ended_at, status: shift.shift.status, target: shift.shift.target_parts, actualGood: shift.kpi.ok_parts, now: demoClock?.now } : null,
  };
}

export interface WorkshopLive {
  stations: Station[];
  kpis: Record<string, Kpi>;
  global: Kpi;
  alerts: Alert[];
  parts: Part[];
  partsComplete: boolean;
}

export type DisplayAlert = Omit<MockAlert, 'shift'> & { shift: string; core?: Alert };
export type DisplayStation = { id: string; deltaVsExpected: number | null; status: StationStatus | null; online?: boolean };
export type DisplayCell = { id: string; good: number; target: number | null; expectedNow: number | null; ko: number; stations: DisplayStation[]; hourly: { hour: number; good: number | null; ko: number }[] | null };
export type DisplayLine = { id: string; name: string; cells: DisplayCell[]; finishedShifts: { code: string; good: number; target: number }[]; cameras: { front: [number | null, number | null]; part: [number | null, number | null] } };
export type WorkshopDisplay = Omit<WorkshopOverview, 'currentShift' | 'dayTarget' | 'lines' | 'problemsByLine'> & {
  currentShift: { code: string; start: string; end: string } | null;
  dayTarget: number | null;
  lines: DisplayLine[];
  problemsByLine: Record<string, Record<AlertCategory, number>>;
  industrial?: WorkshopLive;
};

export function categoryOf(alert: Alert): AlertCategory {
  return alert.use_case === 'safety' ? 'SECURITE_EPI' : alert.use_case === 'workstation' ? 'POSTE' : alert.use_case === 'quality' ? 'QUALITE' : alert.alert_type.includes('camera') ? 'EQUIPEMENT' : 'RYTHME';
}

export function workshopDisplay(source: WorkshopLive): { overview: WorkshopDisplay; alerts: DisplayAlert[] } {
  const currentAlerts = active(source.alerts);
  const cells = [...new Set(source.stations.map((station) => station.cell))].map((cell): DisplayCell => {
    const members = source.stations.filter((station) => station.cell === cell);
    const stationIds = new Set(members.map((station) => station.station_id));
    const recentParts = source.parts.filter((part) => stationIds.has(part.station_id));
    const hours = hourly(recentParts, source.partsComplete, new Date(Date.now() - 8 * 3600000));
    return {
      id: cell, good: members.reduce((sum, station) => sum + (source.kpis[station.station_id]?.ok_parts ?? 0), 0),
      target: null, expectedNow: null,
      ko: members.reduce((sum, station) => sum + (source.kpis[station.station_id]?.nok_parts ?? 0), 0),
      stations: members.map((station) => {
        const alert = currentAlerts.find((item) => item.station_id === station.station_id);
        const camera = station.equipment.find((item) => item.equipment_type === 'camera');
        const status: StationStatus | null = alert?.use_case === 'safety' ? 'SECURITE' : alert?.use_case === 'quality' ? 'QUALITE' : alert?.use_case === 'workstation' ? 'OBJET' : camera?.status === 'down' ? 'CAMERA' : null;
        const expected = station.current_shift?.kpi.expected_ok_parts_by_now;
        return { id: station.station_id, deltaVsExpected: expected == null ? null : station.current_shift!.kpi.ok_parts - expected, status, online: station.online };
      }),
      hourly: hours?.map((item) => ({ ...item, ko: recentParts.filter((part) => part.effective_verdict === 'NOK' && new Date(part.created_at).getHours() === item.hour).length })) ?? null,
    };
  });
  const cameras = source.stations.flatMap((station) => station.equipment.filter((item) => item.equipment_type === 'camera'));
  const categories = {} as Record<AlertCategory, number>;
  for (const alert of currentAlerts) categories[categoryOf(alert)] = (categories[categoryOf(alert)] ?? 0) + 1;
  const line: DisplayLine = {
    id: 'unconfigured', name: 'Ligne non configurée', cells, finishedShifts: [],
    cameras: { front: [null, null], part: [cameras.length ? cameras.filter((camera) => camera.status === 'ok').length : null, null] },
  };
  const overview: WorkshopDisplay = {
    date: new Date().toLocaleDateString('fr-FR'), currentShift: null, dayTarget: null,
    lines: [line], koDay: source.global.nok_parts, koByShift: {},
    problemsByLine: { [line.id]: categories }, industrial: source,
  };
  const alerts: DisplayAlert[] = currentAlerts.map((alert) => ({
    id: alert.alert_id, lineId: line.id, stationId: alert.station_id, category: categoryOf(alert),
    title: alert.title, detail: `${alert.occurrences} observation(s)${alert.simulated ? ' · synthétiques' : ''}`,
    shift: source.stations.find((station) => station.station_id === alert.station_id)?.current_shift?.shift.name ?? 'inconnu',
    when: clockTime(alert.last_seen_at), priority: alert.severity === 'critical',
    action: 'VALIDATE', core: alert,
  }));
  return { overview, alerts };
}

export async function workshopView(): Promise<WorkshopLive> {
  const [stations, global, alerts, parts] = await Promise.all([
    industrial.stations(), industrial.kpi(), industrial.alerts(), industrial.allParts(500),
  ]);
  const kpis: Record<string, Kpi> = {};
  for (let index = 0; index < stations.length; index += 4) {
    const group = stations.slice(index, index + 4);
    const values = await Promise.all(group.map((station) => industrial.kpi(station.station_id)));
    group.forEach((station, offset) => { kpis[station.station_id] = values[offset]; });
  }
  return { stations, global, alerts, kpis, parts, partsComplete: parts.length < 500 };
}

export async function cellView(stationId: string) {
  const [station, alerts, parts] = await Promise.all([
    industrial.station(stationId), industrial.alerts(stationId), industrial.parts(stationId, 1),
  ]);
  return { station, alerts: active(alerts), part: parts[0] ?? null };
}

export async function detailView(stationId: string) {
  const [station, kpi, parts, events, alerts] = await Promise.all([
    industrial.station(stationId), industrial.kpi(stationId), industrial.parts(stationId, 100),
    industrial.events(stationId, 100), industrial.alerts(stationId),
  ]);
  return { station, kpi, parts, events, alerts };
}
