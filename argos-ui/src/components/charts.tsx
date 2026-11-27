// Graphiques dessinés à la main (SVG / div) : aucune librairie à installer.
import { fmt } from './ui';

/** Anneau d'avancement de l'objectif avec un repère « où on devrait être ». */
export function ProgressRing({ value, target, expected, size = 220 }: { value: number; target: number; expected: number; size?: number }) {
  const r = 110, c = 2 * Math.PI * r;
  const done = Math.min(1, value / target);
  const a = (-90 + (expected / target) * 360) * (Math.PI / 180);
  const p = (rad: number) => [140 + rad * Math.cos(a), 140 + rad * Math.sin(a)];
  const [x1, y1] = p(92), [x2, y2] = p(128);
  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} viewBox="0 0 280 280" role="img" aria-label={`${value} pièces bonnes sur ${target}`}>
        <circle cx="140" cy="140" r={r} fill="none" stroke="var(--track)" strokeWidth="30" />
        <circle cx="140" cy="140" r={r} fill="none" stroke="var(--green)" strokeWidth="30" strokeDasharray={`${done * c} ${c}`} transform="rotate(-90 140 140)" />
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--navy)" strokeWidth="5" strokeLinecap="round" />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <span className="num" style={{ fontSize: size * 0.27, color: 'var(--green-text)' }}>{value}</span>
        <span className="muted" style={{ fontSize: 17, fontWeight: 600 }}>sur {fmt(target)}</span>
      </div>
    </div>
  );
}

export interface ShiftGaugeInput {
  startedAt: string;
  plannedEndAt: string;
  endedAt?: string | null;
  status: 'OPEN' | 'CLOSED';
  now: string;
  target: number | null;
  actualGood: number | null;
}

/** One time axis and one cumulative target axis for a complete shift. */
export function shiftGaugeState(input: ShiftGaugeInput) {
  if (input.status === 'CLOSED' && !input.endedAt) return null;
  const start = new Date(input.startedAt).getTime();
  const end = new Date(input.plannedEndAt).getTime();
  const now = new Date(input.status === 'CLOSED' && input.endedAt ? input.endedAt : input.now).getTime();
  if (![start, end, now].every(Number.isFinite) || end <= start || input.target == null || input.target <= 0) return null;
  const target = input.target;
  const elapsed = Math.max(0, Math.min(end - start, now - start));
  const timeRatio = elapsed / (end - start);
  const before = now < start;
  const finished = input.status === 'CLOSED';
  const actual = input.actualGood;
  const expected = finished ? target : target * timeRatio;
  const actualRatio = before || actual == null ? 0 : Math.max(0, Math.min(1, actual / target));
  const deficit = expected > 0 && actual != null ? (expected - actual) / expected : null;
  const tone = before || deficit == null ? 'unknown' : deficit <= 0 ? 'green' : deficit <= 0.1 ? 'amber' : 'red';
  const count = Math.ceil((end - start) / 3600000);
  const ticks = Array.from({ length: count + 1 }, (_, index) => {
    const at = Math.min(end, start + index * 3600000);
    const date = new Date(at);
    const minute = date.getMinutes();
    return {
      position: ((at - start) / (end - start)) * 100,
      hour: `${date.getHours()}h${minute ? String(minute).padStart(2, '0') : ''}`,
      target: Math.round(target * (at - start) / (end - start)),
    };
  });
  return { ticks, timeRatio, actualRatio, actual, expected, target, tone, before, finished, hourlyTarget: target / ((end - start) / 3600000) };
}

/** Continuous operator gauge: fill = good parts, fine marker = target due now. */
export function HourlyGauges({ timeline, height = 56 }: { timeline: ShiftGaugeInput | null; height?: number }) {
  const state = timeline ? shiftGaugeState(timeline) : null;
  return (
    <div className="col" style={{ gap: 8, borderTop: '1px solid var(--line-soft)', paddingTop: 12 }}>
      <div className="between" style={{ flexWrap: 'wrap', gap: 8 }}>
        <span className="label-caps">Heure par heure</span>
        <span className="muted" style={{ fontSize: 14 }}>{state ? `objectif ${state.hourlyTarget.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} pièces bonnes / h` : 'Objectif ou durée du shift indisponible'}</span>
      </div>
      {!state ? <div className="muted" style={{ minHeight: height, display: 'grid', placeItems: 'center', borderRadius: 12, background: 'var(--surface-soft)' }}>Jauge indisponible : aucun shift avec objectif exploitable.</div> : (
        <div style={{ overflowX: 'auto', paddingBottom: 4 }}>
          <div style={{ minWidth: Math.max(480, (state.ticks.length - 1) * 64), padding: '0 2px' }}>
            <div style={{ height: 25, position: 'relative', fontSize: 12, fontWeight: 700 }}>
              {state.ticks.map((tick, index) => <span key={`${tick.position}-top`} style={{ position: 'absolute', left: `${tick.position}%`, transform: index === 0 ? 'none' : index === state.ticks.length - 1 ? 'translateX(-100%)' : 'translateX(-50%)', color: state.timeRatio * 100 >= tick.position ? 'var(--ink)' : 'var(--muted)' }}>{tick.hour}</span>)}
            </div>
            <div role="img" aria-label={`${state.actual ?? 'inconnu'} pièces bonnes sur ${state.target}, ${Math.round(state.timeRatio * 100)} % du temps du shift écoulé`} style={{ position: 'relative', height }}>
              <div style={{ position: 'absolute', inset: 0, borderRadius: 12, background: 'var(--track)', overflow: 'hidden' }}>
                <div style={{ width: `${state.actualRatio * 100}%`, height: '100%', background: state.tone === 'green' ? 'var(--green)' : state.tone === 'amber' ? 'var(--amber)' : state.tone === 'red' ? 'var(--red)' : 'var(--line-strong)', transition: 'width .5s ease' }} />
                {state.ticks.slice(1, -1).map((tick) => <span key={`${tick.position}-mark`} style={{ position: 'absolute', left: `${tick.position}%`, top: 0, bottom: 0, width: 1, background: 'rgba(11,31,63,.25)' }} />)}
              </div>
              <span title={`Objectif théorique actuel : ${Math.round(state.expected).toLocaleString('fr-FR')} pièces bonnes`} style={{ position: 'absolute', left: `${state.timeRatio * 100}%`, top: -5, bottom: -5, width: 3, background: 'var(--navy)', transform: 'translateX(-50%)', borderRadius: 2 }} />
            </div>
            <div style={{ height: 28, position: 'relative', fontSize: 12, fontWeight: 700 }}>
              {state.ticks.map((tick, index) => <span key={`${tick.position}-bottom`} style={{ position: 'absolute', left: `${tick.position}%`, transform: index === 0 ? 'none' : index === state.ticks.length - 1 ? 'translateX(-100%)' : 'translateX(-50%)' }}>{tick.target.toLocaleString('fr-FR')}</span>)}
            </div>
          </div>
        </div>
      )}
      {state && <span className="muted" style={{ fontSize: 13 }}>{state.before ? 'Shift non commencé · jauge vide' : state.finished ? 'Shift terminé · résultat final figé' : 'Production en cours'} · {state.actual == null ? 'production indisponible' : `${state.actual.toLocaleString('fr-FR')} / ${state.target.toLocaleString('fr-FR')} pièces bonnes`} · objectif actuel {Math.round(state.expected).toLocaleString('fr-FR')} · {state.actual == null || state.before ? 'écart indisponible' : `écart ${state.actual - Math.round(state.expected) >= 0 ? '+' : '−'}${Math.abs(state.actual - Math.round(state.expected)).toLocaleString('fr-FR')}`}</span>}
    </div>
  );
}

/** Barres par heure avec ligne d'objectif (superviseur). */
export function HourlyBars({ hours, perHour, currentHour, barMax = 120 }: { hours: { hour: number; good: number | null; ko: number }[]; perHour: number | null; currentHour: number; barMax?: number }) {
  const scale = perHour && perHour > 0 ? perHour : Math.max(1, ...hours.map((item) => item.good ?? 0));
  return (
    <div style={{ position: 'relative', display: 'flex', alignItems: 'flex-end', gap: 14, paddingTop: 20 }}>
      {perHour != null && <div style={{ position: 'absolute', left: 0, right: 0, bottom: 40 + barMax, height: 2, background: 'var(--navy)' }} />}
      {hours.map((h) => (
        <div key={h.hour} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          <span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>{h.good ?? ''}</span>
          {h.good === null
            ? <div style={{ width: '100%', height: barMax, border: '2px dashed var(--line-strong)', borderRadius: '8px 8px 3px 3px' }} />
            : <div style={{ width: '100%', height: Math.round((h.good / scale) * barMax), borderRadius: '8px 8px 3px 3px', background: h.hour === currentHour ? 'var(--green-light)' : 'var(--green)' }} />}
          <span style={{ fontSize: 13, fontWeight: 700, height: 16, color: h.ko ? 'var(--red-text)' : 'transparent' }}>{h.ko ? `${h.ko} KO` : ''}</span>
          <span className="muted" style={{ fontSize: 13, height: 16 }}>{h.hour} h</span>
        </div>
      ))}
    </div>
  );
}

export interface Category { key: string; name: string; color: string }

/** Histogramme empilé : une colonne par groupe, un segment par catégorie. */
export function StackedHistogram({ groups, categories, onPick, height = 280 }: {
  groups: { key: string; name: string; values: Record<string, number> }[];
  categories: Category[];
  onPick?: (key: string) => void;
  height?: number;
}) {
  const totals = groups.map((g) => categories.reduce((s, c) => s + (g.values[c.key] ?? 0), 0));
  const max = Math.max(...totals, 1);
  return (
    <div className="col" style={{ gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-around', gap: 30, borderBottom: '2px solid var(--line)', padding: '0 20px', height: height + 40 }}>
        {groups.map((g, i) => (
          <button key={g.key} onClick={() => onPick?.(g.key)} style={{ width: 120, border: 'none', background: 'none', padding: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
            <span className="num" style={{ fontSize: 26 }}>{totals[i]}</span>
            <div style={{ width: '100%', display: 'flex', flexDirection: 'column-reverse', borderRadius: '8px 8px 0 0', overflow: 'hidden' }}>
              {categories.map((c) => (
                <div key={c.key} title={`${c.name} : ${g.values[c.key] ?? 0}`} style={{ height: ((g.values[c.key] ?? 0) / max) * height, background: c.color }} />
              ))}
            </div>
          </button>
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-around', padding: '0 20px' }}>
        {groups.map((g) => <span key={g.key} style={{ width: 120, textAlign: 'center', fontWeight: 700, fontSize: 15 }}>{g.name}</span>)}
      </div>
      <Legend categories={categories} />
    </div>
  );
}

export function Legend({ categories }: { categories: Category[] }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 18, fontSize: 14 }}>
      {categories.map((c) => (
        <span key={c.key} className="row" style={{ gap: 6 }}><span style={{ width: 12, height: 12, borderRadius: 3, background: c.color }} />{c.name}</span>
      ))}
    </div>
  );
}

/** Anneau de répartition. */
export function Donut({ items, size = 190, centerLabel }: { items: { name: string; value: number; color: string }[]; size?: number; centerLabel: string }) {
  const actualTotal = items.reduce((s, i) => s + i.value, 0);
  const total = actualTotal || 1;
  const r = 78, c = 2 * Math.PI * r;
  let cum = 0;
  return (
    <div className="row stack-mobile" style={{ gap: 20 }}>
      <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
        <svg width={size} height={size} viewBox="0 0 200 200" role="img" aria-label={`Répartition de ${total} ${centerLabel}`}>
          <circle cx="100" cy="100" r={r} fill="none" stroke="var(--line-soft)" strokeWidth="34" />
          {items.map((i) => {
            const f = i.value / total;
            const el = <circle key={i.name} cx="100" cy="100" r={r} fill="none" stroke={i.color} strokeWidth="34" strokeDasharray={`${f * c} ${c}`} strokeDashoffset={-cum * c} transform="rotate(-90 100 100)" />;
            cum += f;
            return el;
          })}
        </svg>
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          <span className="num" style={{ fontSize: 44 }}>{actualTotal}</span>
          <span className="muted" style={{ fontSize: 14 }}>{centerLabel}</span>
        </div>
      </div>
      <div className="col grow" style={{ gap: 8 }}>
        {items.map((i) => (
          <div key={i.name} className="row" style={{ gap: 8, fontSize: 15 }}>
            <span style={{ width: 12, height: 12, borderRadius: 3, background: i.color }} />
            <span className="grow">{i.name}</span>
            <b>{i.value}</b>
            <span className="muted" style={{ width: 40, textAlign: 'right' }}>{Math.round((i.value / total) * 100)} %</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Courbes de santé avec seuil (AI Leader). */
export function HealthChart({ series, threshold, min = 70, max = 100 }: { series: { name: string; values: number[]; color: string }[]; threshold: number; min?: number; max?: number }) {
  const W = 760, H = 170, x0 = 40, x1 = 740;
  const y = (v: number) => ((max - v) / (max - min)) * 150 + 5;
  const n = series[0]?.values.length ?? 1;
  const x = (i: number) => x0 + (i * (x1 - x0)) / Math.max(1, n - 1);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label="Santé des modèles sur 14 jours">
      {[100, 90, 80, 70].map((v) => (
        <g key={v}>
          <line x1={x0} y1={y(v)} x2={x1} y2={y(v)} stroke="var(--line-soft)" />
          <text x={30} y={y(v) + 4} fontSize="12" fill="var(--muted)" textAnchor="end">{v} %</text>
        </g>
      ))}
      <line x1={x0} y1={y(threshold)} x2={x1} y2={y(threshold)} stroke="var(--red)" strokeWidth="2" strokeDasharray="6 5" />
      <text x={x1} y={y(threshold) - 6} fontSize="12" fontWeight="700" fill="var(--red-text)" textAnchor="end">seuil {threshold} %</text>
      {series.map((s) => (
        <polyline key={s.name} points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(' ')} fill="none" stroke={s.color} strokeWidth="3" strokeLinejoin="round" />
      ))}
    </svg>
  );
}
