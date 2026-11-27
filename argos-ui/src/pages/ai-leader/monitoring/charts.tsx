import type { ReactNode } from 'react';

/* Graphiques SVG du Monitoring (aucune bibliothèque) : uniquement des données renvoyées par
   l'API. Une série d'un seul point est affichée comme un point avec son résumé, jamais
   prolongée ni interpolée. */

const W = 560;

/** Vertical bars (score distribution…). */
export function Bars({ counts, labels, color = 'var(--primary)', height = 150, caption }: {
  counts: number[]; labels: string[]; color?: string; height?: number; caption?: ReactNode;
}) {
  const max = Math.max(1, ...counts);
  const bw = W / Math.max(1, counts.length);
  return (
    <figure className="mon-fig">
      <svg viewBox={`0 0 ${W} ${height + 22}`} role="img" aria-label={labels.map((l, i) => `${l} : ${counts[i]}`).join(', ')}>
        <line x1="0" x2={W} y1={height} y2={height} className="mon-axis" />
        {counts.map((c, i) => {
          const h = (c / max) * (height - 8);
          return (
            <g key={i}>
              <rect x={i * bw + 2} y={height - h} width={Math.max(1, bw - 4)} height={h} rx="3" fill={color}><title>{`${labels[i]} : ${c}`}</title></rect>
              {(counts.length <= 12 || i % Math.ceil(counts.length / 10) === 0) && <text x={i * bw + bw / 2} y={height + 15} textAnchor="middle" className="mon-tick">{labels[i]}</text>}
            </g>
          );
        })}
      </svg>
      {caption && <figcaption className="muted">{caption}</figcaption>}
    </figure>
  );
}

/** Reference vs observed proportions on the SAME bins (juxtaposed bars). */
export function PairedBars({ labels, reference, current, height = 170 }: { labels: string[]; reference: number[]; current: number[] | null; height?: number }) {
  const max = Math.max(0.01, ...reference, ...(current ?? []));
  const bw = W / Math.max(1, labels.length);
  const half = (bw - 6) / 2;
  return (
    <figure className="mon-fig">
      <svg viewBox={`0 0 ${W} ${height + 22}`} role="img" aria-label="Distribution des scores : référence et population observée">
        <line x1="0" x2={W} y1={height} y2={height} className="mon-axis" />
        {labels.map((l, i) => {
          const hr = (reference[i] / max) * (height - 8);
          const hc = current ? (current[i] / max) * (height - 8) : 0;
          return (
            <g key={i}>
              <rect x={i * bw + 3} y={height - hr} width={half} height={hr} rx="2" fill="var(--primary-light)"><title>{`${l} · référence : ${(reference[i] * 100).toFixed(1)} %`}</title></rect>
              {current && <rect x={i * bw + 3 + half} y={height - hc} width={half} height={hc} rx="2" fill="var(--red)"><title>{`${l} · observé : ${(current[i] * 100).toFixed(1)} %`}</title></rect>}
              <text x={i * bw + bw / 2} y={height + 15} textAnchor="middle" className="mon-tick">{l}</text>
            </g>
          );
        })}
      </svg>
      <figcaption className="row" style={{ gap: 16 }}>
        <span className="row" style={{ gap: 6 }}><span className="hv-dot" style={{ background: 'var(--primary-light)' }} />Référence</span>
        {current && <span className="row" style={{ gap: 6 }}><span className="hv-dot" style={{ background: 'var(--red)' }} />Population observée</span>}
        <span className="muted">proportions par classe de score (bords fixés sur la référence)</span>
      </figcaption>
    </figure>
  );
}

export interface SeriesDef { name: string; color: string }

/** Time series from real points only; one point = a dot plus its summary. */
export function Series({ points, series, format, height = 160, empty }: {
  points: { x: string; values: Record<string, number | null> }[]; series: SeriesDef[]; format: (v: number) => string; height?: number; empty: ReactNode;
}) {
  if (!points.length) return <div className="mon-empty">{empty}</div>;
  const all = points.flatMap((p) => series.map((s) => p.values[s.name])).filter((v): v is number => v != null);
  const max = Math.max(1e-9, ...all) * 1.1;
  const pad = 36;
  const x = (i: number) => (points.length === 1 ? W / 2 : pad + (i * (W - 2 * pad)) / (points.length - 1));
  const y = (v: number) => height - (v / max) * (height - 12);
  return (
    <figure className="mon-fig">
      <svg viewBox={`0 0 ${W} ${height + 22}`} role="img" aria-label={series.map((s) => s.name).join(', ')}>
        <line x1="0" x2={W} y1={height} y2={height} className="mon-axis" />
        {series.map((s) => {
          const pts = points.map((p, i) => [i, p.values[s.name]] as const).filter((p): p is readonly [number, number] => p[1] != null);
          return (
            <g key={s.name}>
              {pts.length > 1 && <polyline fill="none" stroke={s.color} strokeWidth="2.5" points={pts.map(([i, v]) => `${x(i)},${y(v)}`).join(' ')} />}
              {pts.map(([i, v]) => <circle key={i} cx={x(i)} cy={y(v)} r={points.length === 1 ? 6 : 3.5} fill={s.color}><title>{`${s.name} · ${points[i].x} : ${format(v)}`}</title></circle>)}
            </g>
          );
        })}
        {points.map((p, i) => (points.length <= 10 || i % Math.ceil(points.length / 8) === 0) && <text key={p.x} x={x(i)} y={height + 15} textAnchor="middle" className="mon-tick">{p.x}</text>)}
      </svg>
      <figcaption className="row" style={{ gap: 16, flexWrap: 'wrap' }}>
        {series.map((s) => <span key={s.name} className="row" style={{ gap: 6 }}><span className="hv-dot" style={{ background: s.color }} />{s.name}</span>)}
        {points.length === 1 && <span className="muted">
          Un seul point collecté ({points[0].x}) : {series.map((s) => `${s.name} ${points[0].values[s.name] == null ? '—' : format(points[0].values[s.name] as number)}`).join(' · ')}
        </span>}
      </figcaption>
    </figure>
  );
}

/** Horizontal counts list (states, alert breakdown). */
export function HBars({ items }: { items: { label: string; count: number; color: string; hint?: string }[] }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <ul className="mon-hbars">
      {items.map((i) => (
        <li key={i.label} title={i.hint}>
          <span className="mon-hbar-label">{i.label}</span>
          <span className="mon-hbar-track"><span style={{ width: `${(i.count * 100) / max}%`, background: i.color }} /></span>
          <b>{i.count}</b>
        </li>
      ))}
    </ul>
  );
}

/** Horizontal comparison of two percentiles per row (P50 light, P95 red), same scale. */
export function LatencyBars({ items, format }: { items: { label: string; p50: number | null; p95: number | null; n: number }[]; format: (v: number | null) => string }) {
  const max = Math.max(1e-9, ...items.flatMap((i) => [i.p50 ?? 0, i.p95 ?? 0]));
  return (
    <div className="col" style={{ gap: 10 }}>
      <ul className="mon-lat">
        {items.map((i) => (
          <li key={i.label}>
            <span className="mon-hbar-label" title={i.label}>{i.label}<small className="muted"> · n={i.n}</small></span>
            <span className="mon-lat-bars">
              <span className="mon-hbar-track"><span style={{ width: `${((i.p50 ?? 0) * 100) / max}%`, background: 'var(--primary-light)' }} title={`P50 ${format(i.p50)}`} /></span>
              <span className="mon-hbar-track"><span style={{ width: `${((i.p95 ?? 0) * 100) / max}%`, background: 'var(--red)' }} title={`P95 ${format(i.p95)}`} /></span>
            </span>
            <span className="mon-lat-values">{format(i.p50)}<br />{format(i.p95)}</span>
          </li>
        ))}
      </ul>
      <span className="row" style={{ gap: 16, fontSize: 13 }}>
        <span className="row" style={{ gap: 6 }}><span className="hv-dot" style={{ background: 'var(--primary-light)' }} />P50</span>
        <span className="row" style={{ gap: 6 }}><span className="hv-dot" style={{ background: 'var(--red)' }} />P95</span>
      </span>
    </div>
  );
}
