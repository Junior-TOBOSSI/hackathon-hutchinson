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

/** Jauges heure par heure (opérateur). */
export function HourlyGauges({ hours, perHour, currentHour, height = 56 }: { hours: { hour: number; good: number | null }[]; perHour: number; currentHour: number; height?: number }) {
  return (
    <div className="col" style={{ gap: 8, borderTop: '1px solid var(--line-soft)', paddingTop: 12 }}>
      <div className="between">
        <span className="label-caps">Heure par heure</span>
        <span className="muted" style={{ fontSize: 14 }}>objectif {perHour} pièces / h · heure en cours en vert clair</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${hours.length}, minmax(0, 1fr))`, gap: 8 }}>
        {hours.map((h) => {
          const cur = h.hour === currentHour;
          const ok = h.good !== null && h.good >= perHour;
          const color = cur ? 'var(--green-light)' : ok ? 'var(--green)' : 'var(--amber)';
          return (
            <div key={h.hour} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <span style={{ fontSize: 14, fontWeight: 700, height: 18, color: ok || cur ? 'var(--green-text)' : 'var(--amber-text)' }}>{h.good ?? ''}</span>
              <div style={{ position: 'relative', width: '100%', height, borderRadius: 8, background: 'var(--track)', overflow: 'hidden' }}>
                {h.good === null
                  ? <div style={{ position: 'absolute', inset: 0, border: '2px dashed var(--line-strong)', borderRadius: 8 }} />
                  : <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: `${Math.min(100, (h.good / perHour) * 100)}%`, background: color }} />}
              </div>
              <span style={{ fontSize: 12, fontWeight: cur ? 700 : 400 }} className={cur ? '' : 'muted'}>{h.hour} h</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Barres par heure avec ligne d'objectif (superviseur). */
export function HourlyBars({ hours, perHour, currentHour, barMax = 120 }: { hours: { hour: number; good: number | null; ko: number }[]; perHour: number; currentHour: number; barMax?: number }) {
  return (
    <div style={{ position: 'relative', display: 'flex', alignItems: 'flex-end', gap: 14, paddingTop: 20 }}>
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 40 + barMax, height: 2, background: 'var(--navy)' }} />
      {hours.map((h) => (
        <div key={h.hour} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          <span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>{h.good ?? ''}</span>
          {h.good === null
            ? <div style={{ width: '100%', height: barMax, border: '2px dashed var(--line-strong)', borderRadius: '8px 8px 3px 3px' }} />
            : <div style={{ width: '100%', height: Math.round((h.good / perHour) * barMax), borderRadius: '8px 8px 3px 3px', background: h.hour === currentHour ? 'var(--green-light)' : 'var(--green)' }} />}
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
  const total = items.reduce((s, i) => s + i.value, 0) || 1;
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
          <span className="num" style={{ fontSize: 44 }}>{total}</span>
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
