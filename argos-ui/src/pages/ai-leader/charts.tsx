/* Graphiques SVG simples, sans dépendance, aux couleurs du thème. */

export interface Bar { label: string; value: number; color?: string; note?: string }
export interface BarGroup { label: string; bars: Bar[] }

const PALETTE = ['var(--navy)', 'var(--primary-light)', 'var(--cat-qualite)', 'var(--cat-rythme)'];

/** Barres horizontales groupées ; ``max`` borne l'échelle (1 pour les ratios). */
export function GroupedBars({ groups, max, format, legend }: { groups: BarGroup[]; max: number; format: (v: number) => string; legend?: { label: string; color: string }[] }) {
  const rowH = 22, gap = 6, labelW = 170, valueW = 70, W = 640;
  const barW = W - labelW - valueW - 10;
  let y = 0;
  const rows: JSX.Element[] = [];
  groups.forEach((g, gi) => {
    rows.push(<text key={`g${gi}`} x={0} y={y + 15} fontSize={14} fontWeight={700} fill="var(--ink)">{g.label}</text>);
    g.bars.forEach((b, bi) => {
      const top = y + bi * (rowH + 4);
      const w = Math.max(2, (Math.min(b.value, max) / max) * barW);
      rows.push(
        <g key={`b${gi}-${bi}`}>
          <text x={labelW - 8} y={top + 15 + 22} fontSize={13} textAnchor="end" fill="var(--muted)">{b.label}</text>
          <rect x={labelW} y={top + 22} width={barW} height={rowH} rx={6} fill="var(--track)" />
          <rect x={labelW} y={top + 22} width={w} height={rowH} rx={6} fill={b.color ?? PALETTE[bi % PALETTE.length]} />
          <text x={labelW + barW + 8} y={top + 15 + 22} fontSize={13} fontWeight={700} fill="var(--ink)">{format(b.value)}</text>
        </g>,
      );
    });
    y += 22 + g.bars.length * (rowH + 4) + gap + 8;
  });
  return (
    <div className="col" style={{ gap: 8 }}>
      {legend && <div className="row" style={{ gap: 16, flexWrap: 'wrap', fontSize: 13 }}>{legend.map((l) => <span key={l.label} className="row" style={{ gap: 6 }}><span style={{ width: 14, height: 14, borderRadius: 4, background: l.color }} />{l.label}</span>)}</div>}
      <svg viewBox={`0 0 ${W} ${Math.max(y, 30)}`} width="100%" style={{ maxWidth: W }} role="img">{rows}</svg>
    </div>
  );
}

/** Indicateurs de dérive : une barre par variable, avec SON seuil (renvoyé par l'API). */
export function DriftBars({ items }: { items: { feature: string; value: number; threshold: number; alert: boolean }[] }) {
  const W = 640, labelW = 150, valueW = 110, rowH = 26;
  const barW = W - labelW - valueW;
  // Échelle commune : au moins 2 × le plus grand seuil, pour que le seuil reste visible.
  const scale = Math.max(...items.map((i) => Math.max(i.value, i.threshold * 2)), 0.0001);
  const H = items.length * (rowH + 18) + 10;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W }} role="img" aria-label="Indicateurs de dérive par variable">
      {items.map((it, i) => {
        const top = i * (rowH + 18) + 4;
        const w = Math.max(2, (it.value / scale) * barW);
        const tx = labelW + (it.threshold / scale) * barW;
        return (
          <g key={it.feature}>
            <text x={labelW - 10} y={top + 18} fontSize={14} textAnchor="end" fill="var(--ink)" fontWeight={600}>{it.feature}</text>
            <rect x={labelW} y={top} width={barW} height={rowH} rx={6} fill="var(--track)" />
            <rect x={labelW} y={top} width={w} height={rowH} rx={6} fill={it.alert ? 'var(--red)' : 'var(--green)'} />
            <line x1={tx} x2={tx} y1={top - 4} y2={top + rowH + 4} stroke="var(--navy)" strokeWidth={2} strokeDasharray="4 3" />
            <text x={tx + 4} y={top + rowH + 14} fontSize={11} fill="var(--muted)">seuil {it.threshold.toLocaleString('fr-FR')}</text>
            <text x={labelW + barW + 10} y={top + 18} fontSize={14} fontWeight={700} fill={it.alert ? 'var(--red-text)' : 'var(--green-text)'}>{it.value.toLocaleString('fr-FR', { maximumFractionDigits: 2 })}</text>
          </g>
        );
      })}
    </svg>
  );
}
