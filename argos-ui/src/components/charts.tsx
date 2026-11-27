// Graphiques dessinés à la main (SVG / div) : aucune librairie à installer.
import { useEffect, useRef, useState, type PointerEvent } from 'react';
import { deltaText, fmt } from './ui';

/* ------------------------------------------------------------------ */
/* Production cumulée de la cellule : réel contre objectif             */
/* ------------------------------------------------------------------ */

/** Largeur réelle d'un élément, pour dessiner le SVG au pixel près (texte jamais déformé). */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(800);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

/**
 * Courbe cumulée « réel contre objectif » sur le shift.
 * - réel : pièces bonnes cumulées depuis le début du shift (trait plein bleu + voile léger) ;
 * - objectif : droite de l'objectif cumulé (trait gris en tirets) ;
 * - l'écart entre les deux à l'instant présent = l'avance ou le retard de la cellule.
 * Survol : un repère vertical s'aligne sur l'heure la plus proche et affiche les valeurs.
 */
export function CumulativeChart({ hourly, target, expectedNow, shiftStart, shiftHours = 8, height = 300 }: {
  hourly: { hour: number; good: number | null }[];
  target: number; // objectif du shift
  expectedNow: number; // pièces attendues maintenant : fixe la position de « maintenant »
  shiftStart: number; // 13 pour 13 h
  shiftHours?: number;
  height?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const perHour = target / shiftHours;
  const now = shiftStart + expectedNow / perHour; // en heures décimales
  const total = hourly.reduce((s, h) => s + (h.good ?? 0), 0);

  // Points du réel : 0 au début du shift, puis le cumul à chaque heure pleine, puis maintenant.
  const points: { x: number; y: number }[] = [{ x: shiftStart, y: 0 }];
  let cum = 0;
  // Un shift peut passer minuit (21 h → 5 h) : après minuit, 0 h compte comme 24 h, 1 h comme 25 h…
  const cont = (hour: number) => (hour < shiftStart ? hour + 24 : hour);
  for (const h of hourly) {
    if (h.good === null) break;
    cum += h.good;
    if (cont(h.hour) + 1 <= now) points.push({ x: cont(h.hour) + 1, y: cum });
  }
  points.push({ x: now, y: total });

  // Géométrie (pixels).
  const pad = { l: 52, r: 150, t: 18, b: 34 };
  const w = Math.max(320, width), iw = w - pad.l - pad.r, ih = height - pad.t - pad.b;
  const X = (hour: number) => pad.l + ((hour - shiftStart) / shiftHours) * iw;
  const Y = (v: number) => pad.t + ih - (v / target) * ih;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(target * f));
  // Un seul format par axe : compact (« 3 k ») dès que l'axe atteint 10 000.
  const tickLabel = (v: number) => (target >= 10000 ? (v ? `${(v / 1000).toLocaleString('fr-FR')} k` : '0') : fmt(v));
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${X(p.x)},${Y(p.y)}`).join(' ');
  const area = `${line} L${X(now)},${Y(0)} L${X(shiftStart)},${Y(0)} Z`;
  const gap = total - expectedNow;
  const hp = hover === null ? null : points[hover];

  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - box.left + pad.l;
    let best = 0;
    points.forEach((p, i) => { if (Math.abs(X(p.x) - px) < Math.abs(X(points[best].x) - px)) best = i; });
    setHover(best);
  };
  const hhmm = (x: number) => `${Math.floor(x) % 24}:${String(Math.round((x % 1) * 60)).padStart(2, '0')}`;

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      {/* Légende : deux séries, donc toujours présente */}
      <div className="row muted" style={{ gap: 18, fontSize: 13, marginBottom: 6 }}>
        <span className="row" style={{ gap: 6 }}><span style={{ width: 18, height: 3, borderRadius: 2, background: 'var(--chart-real)' }} />Pièces bonnes cumulées</span>
        <span className="row" style={{ gap: 6 }}><svg width="18" height="4" aria-hidden="true"><line x1="0" y1="2" x2="18" y2="2" stroke="var(--chart-target)" strokeWidth="2" strokeDasharray="4 3" /></svg>Objectif cumulé</span>
      </div>
      <svg width={w} height={height} role="img" aria-label={`Production cumulée : ${fmt(total)} pièces bonnes, objectif ${fmt(expectedNow)} à cette heure, ${deltaText(gap).toLowerCase()}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Grille et axes : discrets */}
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={pad.l + iw} y1={Y(v)} y2={Y(v)} stroke="var(--line-soft)" strokeWidth="1" />
            <text x={pad.l - 8} y={Y(v) + 4} textAnchor="end" fontSize="12" fill="var(--muted)">{tickLabel(v)}</text>
          </g>
        ))}
        {Array.from({ length: shiftHours + 1 }, (_, i) => shiftStart + i).map((h) => (
          <text key={h} x={X(h)} y={height - 10} textAnchor="middle" fontSize="12" fill="var(--muted)" fontWeight={Math.floor(now) === h ? 700 : 400}>{h % 24} h</text>
        ))}
        {/* Réel */}
        <path d={area} fill="var(--chart-real)" opacity="0.1" />
        <path d={line} fill="none" stroke="var(--chart-real)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {/* Objectif, dessiné APRÈS le réel pour rester visible quand les deux se confondent */}
        <line x1={X(shiftStart)} y1={Y(0)} x2={X(shiftStart + shiftHours)} y2={Y(target)} stroke="var(--chart-target)" strokeWidth="2" strokeDasharray="6 5" />
        <text x={X(shiftStart + shiftHours) + 10} y={Y(target) + 4} fontSize="13" fill="var(--muted)">objectif {fmt(target)}</text>
        {/* Maintenant : l'écart entre le réel et l'objectif */}
        <line x1={X(now)} x2={X(now)} y1={Y(total)} y2={Y(expectedNow)} stroke={gap >= 0 ? 'var(--green)' : 'var(--red)'} strokeWidth="3" />
        <circle cx={X(now)} cy={Y(total)} r="5" fill="var(--chart-real)" stroke="#fff" strokeWidth="2" />
        {/* Étiquettes sous le point : l'objectif monte vers la droite, le dessous reste libre */}
        <text x={X(now) + 12} y={Y(total) + 22} fontSize="14" fontWeight="700" fill="var(--ink)">{fmt(total)} pièces</text>
        <text x={X(now) + 12} y={Y(total) + 40} fontSize="13" fontWeight="700" fill={gap >= 0 ? 'var(--green-text)' : 'var(--red-text)'}>{deltaText(gap, true)}</text>
        {/* Survol */}
        {hp && (
          <g pointerEvents="none">
            <line x1={X(hp.x)} x2={X(hp.x)} y1={pad.t} y2={pad.t + ih} stroke="var(--muted)" strokeWidth="1" />
            <circle cx={X(hp.x)} cy={Y(hp.y)} r="5" fill="var(--chart-real)" stroke="#fff" strokeWidth="2" />
          </g>
        )}
        <rect x={pad.l} y={pad.t} width={iw} height={ih} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
      </svg>
      {hp && (
        <div style={{ position: 'absolute', left: Math.min(X(hp.x) + 12, w - 190), top: 30, background: '#fff', border: '1px solid var(--line)', borderRadius: 10, boxShadow: '0 6px 18px rgba(11,31,63,.12)', padding: '8px 12px', fontSize: 13, pointerEvents: 'none', minWidth: 170 }}>
          <div className="muted" style={{ fontWeight: 600, marginBottom: 4 }}>{hhmm(hp.x)}</div>
          <div className="between"><b>{fmt(hp.y)}</b><span className="muted">réel</span></div>
          <div className="between"><b>{fmt(Math.round(perHour * (hp.x - shiftStart)))}</b><span className="muted">objectif</span></div>
          <div style={{ fontWeight: 700, color: hp.y >= perHour * (hp.x - shiftStart) ? 'var(--green-text)' : 'var(--red-text)' }}>{deltaText(Math.round(hp.y - perHour * (hp.x - shiftStart)), true)}</div>
        </div>
      )}
      {/* Vue tableau pour les lecteurs d'écran */}
      <table style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>
        <caption>Production cumulée de la cellule</caption>
        <thead><tr><th>Heure</th><th>Réel cumulé</th><th>Objectif cumulé</th></tr></thead>
        <tbody>{points.map((p) => <tr key={p.x}><td>{hhmm(p.x)}</td><td>{p.y}</td><td>{Math.round(perHour * (p.x - shiftStart))}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

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

/**
 * Barre du shift (opérateur) : une seule barre cumulée, découpée en heures par des traits.
 * Chaque tronçon vaut l'objectif horaire ; la production s'additionne, donc le surplus
 * d'une heure commence à remplir la suivante. Le trait marine montre où on devrait être.
 *  - tronçon plein : vert ;
 *  - tronçon entamé d'une heure déjà passée : orange (le poste est en retard) ;
 *  - tronçon entamé de l'heure en cours ou à venir : vert clair (en cours).
 */
export function HourlyGauges({ hours, perHour, currentHour, expected, height = 32 }: { hours: { hour: number; good: number | null }[]; perHour: number; currentHour: number; expected?: number; height?: number }) {
  // Une seule barre pour tout le shift : vert si on est dans les temps, rouge si on est en retard.
  const total = hours.reduce((sum, h) => sum + (h.good ?? 0), 0);
  const capacity = hours.length * perHour;
  const late = expected !== undefined && total < expected;
  const color = late ? 'var(--red)' : 'var(--green)';
  const pct = (n: number) => `${Math.min(100, (n / capacity) * 100)}%`;
  const last = hours[hours.length - 1];
  return (
    <div className="col" style={{ gap: 8, borderTop: '1px solid var(--line-soft)', paddingTop: 12 }}>
      <div className="between" style={{ flexWrap: 'wrap' }}>
        <span className="label-caps">Progression du shift</span>
        <span style={{ fontSize: 15, fontWeight: 700, color: color }}>
          {fmt(total)} / {fmt(capacity)}{expected !== undefined && <span className="muted" style={{ fontWeight: 500 }}> · attendu maintenant {fmt(expected)}</span>}
        </span>
      </div>
      <div style={{ position: 'relative' }}>
        <div style={{ height, borderRadius: height / 2, background: 'var(--track)', overflow: 'hidden' }}>
          <div style={{ width: pct(total), height: '100%', background: color, borderRadius: height / 2 }} />
        </div>
      </div>
      {/* Les heures, en dessous de la barre */}
      <div style={{ position: 'relative', height: 18 }}>
        {[...hours.map((h) => h.hour), last ? (last.hour + 1) % 24 : null].filter((h): h is number => h !== null).map((h, i) => (
          <span key={i} style={{ position: 'absolute', left: `${(i / hours.length) * 100}%`, transform: i === 0 ? 'none' : i === hours.length ? 'translateX(-100%)' : 'translateX(-50%)', whiteSpace: 'nowrap', fontSize: 13, fontWeight: h === currentHour ? 700 : 400, color: h === currentHour ? 'var(--ink)' : 'var(--muted)' }}>{h} h</span>
        ))}
      </div>
    </div>
  );
}

/** Barres par heure avec ligne d'objectif (team leader, production de la cellule). */
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
          <span style={{ fontSize: 13, fontWeight: 700, height: 16, color: h.ko ? 'var(--red-text)' : 'transparent' }}>{h.ko ? `${h.ko} NOK` : ''}</span>
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
