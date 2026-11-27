import { useState, type ReactNode } from 'react';
import { Icon, ICONS } from '../../components/ui';
import './ui.css';

/* Petits composants partagés par les sections AI Leader (Datasets, Training Factory),
   construits sur le thème HOVIS existant : aucune nouvelle bibliothèque. */

export type IconName = keyof typeof ICONS;

/** Carte KPI : icône dans un carré bleu clair, titre, valeur, précision. */
export function Kpi({ icon, label, value, hint, tone }: { icon: IconName; label: string; value: ReactNode; hint?: ReactNode; tone?: 'green' | 'red' | 'amber' }) {
  return (
    <div className="card hv-kpi">
      <span className="hv-kpi-icon"><Icon d={ICONS[icon]} size={20} /></span>
      <div className="hv-kpi-body">
        <span className="hv-kpi-label">{label}</span>
        <span className={`hv-kpi-value${tone ? ` hv-${tone}` : ''}`}>{value}</span>
        {hint && <span className="hv-kpi-hint">{hint}</span>}
      </div>
    </div>
  );
}

const SEARCH = 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M20 20l-4-4';
const FILTER = 'M4 5h16l-6 8v6l-4-2v-4z';

export function SearchField({ value, onChange, placeholder, label }: { value: string; onChange: (v: string) => void; placeholder: string; label?: string }) {
  return (
    <label className="hv-field hv-search" aria-label={label ?? placeholder}>
      <Icon d={SEARCH} size={16} />
      <input className="hv-input" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} maxLength={100} />
    </label>
  );
}

/** Sélecteur HOVIS (select natif pour l'accessibilité, apparence harmonisée). */
export function SelectField({ value, onChange, options, label, icon = 'filter', allLabel }: {
  value: string; onChange: (v: string) => void; options: [string, string][]; label: string; icon?: 'filter' | 'sort' | 'none'; allLabel?: string;
}) {
  return (
    <label className="hv-field hv-select" title={label}>
      {icon !== 'none' && <Icon d={icon === 'sort' ? 'M7 4v16 M3 16l4 4 4-4 M17 20V4 M13 8l4-4 4 4' : FILTER} size={15} />}
      <select className="hv-input" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {allLabel !== undefined && <option value="">{allLabel}</option>}
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

export function Chip({ tone = 'grey', children, title }: { tone?: 'green' | 'red' | 'amber' | 'blue' | 'grey' | 'navy'; children: ReactNode; title?: string }) {
  return <span className={`hv-chip hv-chip-${tone}`} title={title}>{children}</span>;
}

const pct = (n: number, total: number) => (total ? `${((n * 100) / total).toFixed(1).replace('.', ',')} %` : '0 %');

/** Anneau générique : couleurs fournies par l'appelant (aucune classe codée en dur). */
export function Donut({ items, centerLabel = 'images', size = 168 }: { items: { label: string; count: number; color: string }[]; centerLabel?: string; size?: number }) {
  const [hover, setHover] = useState<string | null>(null);
  const total = items.reduce((n, i) => n + i.count, 0);
  const r = 15.9155; // circumference = 100
  let offset = 25;
  const shown = items.find((i) => i.label === hover);
  return (
    <div className="hv-donut">
      <svg viewBox="0 0 42 42" width={size} height={size} role="img" aria-label={`Distribution : ${items.map((i) => `${i.label} ${i.count}`).join(', ')}`}>
        <circle cx="21" cy="21" r={r} fill="none" stroke="var(--track)" strokeWidth="6" />
        {total > 0 && items.filter((i) => i.count > 0).map((i) => {
          const len = (i.count * 100) / total;
          const el = (
            <circle key={i.label} cx="21" cy="21" r={r} fill="none" stroke={i.color} strokeWidth={hover === i.label ? 7.2 : 6}
              strokeDasharray={`${len} ${100 - len}`} strokeDashoffset={offset} onMouseEnter={() => setHover(i.label)} onMouseLeave={() => setHover(null)}>
              <title>{`${i.label} : ${i.count.toLocaleString('fr-FR')} (${pct(i.count, total)})`}</title>
            </circle>
          );
          offset -= len;
          return el;
        })}
        <text x="21" y="20.5" textAnchor="middle" className="hv-donut-total">{(shown?.count ?? total).toLocaleString('fr-FR')}</text>
        <text x="21" y="25.5" textAnchor="middle" className="hv-donut-sub">{shown ? shown.label : centerLabel}</text>
      </svg>
      <ul className="hv-legend">
        {items.map((i) => (
          <li key={i.label} onMouseEnter={() => setHover(i.label)} onMouseLeave={() => setHover(null)}>
            <span className="hv-dot" style={{ background: i.color }} /><span className="hv-legend-label">{i.label}</span>
            <b>{i.count.toLocaleString('fr-FR')}</b><span className="muted">{pct(i.count, total)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export const SPLIT_BLUES = ['var(--navy)', 'var(--primary)', '#8fb4e8'];

/** Barre horizontale empilée unique (ex. train / validation / test). */
export function StackedBar({ items }: { items: { label: string; count: number; color: string }[] }) {
  const total = items.reduce((n, i) => n + i.count, 0);
  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="hv-stack" role="img" aria-label={items.map((i) => `${i.label} ${i.count}`).join(', ')}>
        {items.filter((i) => i.count > 0).map((i) => (
          <span key={i.label} style={{ width: `${(i.count * 100) / total}%`, background: i.color }} title={`${i.label} : ${i.count} (${pct(i.count, total)})`} />
        ))}
      </div>
      <ul className="hv-legend hv-legend-row">
        {items.map((i) => (
          <li key={i.label}><span className="hv-dot" style={{ background: i.color }} /><span className="hv-legend-label">{i.label}</span>
            <b>{i.count.toLocaleString('fr-FR')}</b><span className="muted">{pct(i.count, total)}</span></li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ libellés français */

const FR: Record<string, string> = {
  random: 'aléatoire', 'random (stratified, seeded)': 'aléatoire (stratifié, graine fixe)', by_sequence: 'par séquence',
  by_time: 'par période', by_station: 'par poste', by_burst: 'par rafale',
  validated: 'validées', corrected: 'corrigées', excluded: 'exclues', imported: 'importées',
  quality: 'Qualité', workstation: 'Poste de travail / 5S', safety: 'Sécurité',
  classification: 'classification', detection: 'détection', none: 'non revue',
};
export const fr = (key: string | null | undefined) => (key == null ? '—' : FR[key] ?? key);
const REVIEW_SINGULAR: Record<string, string> = { validated: 'validée', corrected: 'corrigée', imported: 'importée', none: 'non revue' };
export const frReview = (key: string | null | undefined) => (key ? REVIEW_SINGULAR[key] ?? key : 'non revue');

/* ------------------------------------------------------------------ couleurs de classes */

const PALETTE = ['#2f6fd6', '#7a5af5', '#0f9d9a', '#e08a1e', '#c2417a', '#5b8c2a', '#8d6e63', '#3c4a63'];

/** Couleur stable par classe : sémantique pour les classes de conformité, sinon palette
    déterministe (même classe = même couleur partout). */
export function classColor(label: string, index: number): string {
  const l = label.toUpperCase();
  if (l === 'OK' || l === 'GOOD') return 'var(--green)';
  if (l === 'NOK') return 'var(--red)';
  if (l.startsWith('NOK_')) return ['var(--red)', '#e08a1e', '#c2417a'][index % 3];
  let h = 0;
  for (const ch of label) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
