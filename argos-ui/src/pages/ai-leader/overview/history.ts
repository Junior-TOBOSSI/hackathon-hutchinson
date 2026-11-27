// Pure logic of the home page (DBX-09), tested with `node --test` (no extra dependency).

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown';
export interface RunLike { status: RunStatus; started_at: string | null }

/** Status groups shown in the training history (every status belongs to exactly one). */
export const RUN_GROUPS: [RunStatus[], string, string][] = [
  [['succeeded'], 'Réussis', 'var(--green)'],
  [['failed'], 'Échoués', 'var(--red)'],
  [['running', 'queued'], 'En cours', 'var(--primary-light)'],
  [['cancelled', 'unknown'], 'Annulés / inconnus', 'var(--line-strong)'],
];

export const groupOf = (s: RunStatus): string => RUN_GROUPS.find(([g]) => g.includes(s))?.[1] ?? 'Annulés / inconnus';

/** Monday (local time) of the week containing `t`, as YYYY-MM-DD. */
function weekKey(t: Date): string {
  const m = new Date(t.getFullYear(), t.getMonth(), t.getDate() - ((t.getDay() + 6) % 7));
  return `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, '0')}-${String(m.getDate()).padStart(2, '0')}`;
}
function dayKey(t: Date): string {
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`;
}

/** Real runs of the period, grouped by local day (<= 30 days) or week (longer periods).
    Runs without a start date are not placed on the time axis; empty periods are not created. */
export function bucketRuns<T extends RunLike>(all: T[], period: string, now: number = Date.now()) {
  const since = period === 'all' ? null : now - Number(period) * 86400_000;
  const runs = all.filter((r) => r.started_at && (since === null || new Date(r.started_at).getTime() >= since));
  const weekly = period === 'all' || Number(period) > 30;
  const map = new Map<string, Record<string, number>>();
  for (const r of runs) {
    const t = new Date(r.started_at as string);
    const k = weekly ? weekKey(t) : dayKey(t);
    const b = map.get(k) ?? {};
    b[groupOf(r.status)] = (b[groupOf(r.status)] ?? 0) + 1;
    map.set(k, b);
  }
  return { runs, weekly, buckets: [...map.entries()].sort(([a], [b]) => a.localeCompare(b)) };
}

const REASONS: [RegExp, string][] = [
  [/(\d+) manual request\(s\) by (.+)/, '$1 demande(s) manuelle(s) de $2'],
  [/persistent drift on (\d+) distinct windows/, 'dérive persistante sur $1 fenêtres distinctes'],
  [/(\d+) new or modified validated annotations/, '$1 annotations validées nouvelles ou modifiées'],
  [/(\d+) days elapsed since the last training/, '$1 jours écoulés depuis le dernier entraînement'],
];
/** French rendering of known backend reasons (unknown texts are kept as they are). */
export const frReason = (text: string | null): string | null =>
  text == null ? null : REASONS.reduce((t, [re, rep]) => t.replace(re, rep), text);
