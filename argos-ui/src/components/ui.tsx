import type { CSSProperties, ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';
import { HovisLogo } from './brand';

/* Icônes au trait (24×24). */
export const ICONS = {
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z',
  shieldAlert: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z M12 9v4 M12 16h.01',
  grid: 'M4 4h16v16H4z M4 12h16 M12 4v16',
  check: 'm5 12 5 5 9-10',
  flag: 'M5 21V4 M5 4h11l-2 4 2 4H5',
  warn: 'M12 3 2 20h20L12 3z M12 10v4 M12 17h.01',
  overview: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  bars: 'M4 20V10 M10 20V4 M16 20v-7 M22 20H2',
  camera: 'M3 7h4l2-3h6l2 3h4v12H3z M12 10a3 3 0 1 0 0 6a3 3 0 1 0 0-6',
  home: 'M3 11l9-8 9 8v10H3z',
  layers: 'M12 3l9 5-9 5-9-5 9-5z M3 13l9 5 9-5',
  db: 'M4 6c0-2 16-2 16 0v12c0 2-16 2-16 0z M4 6c0 2 16 2 16 0',
  play: 'M5 3v18l15-9z',
  monitor: 'M3 4h18v12H3z M8 20h8 M12 16v4',
  users: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M22 21v-2a4 4 0 0 0-3-3.9 M16 3.1a4 4 0 0 1 0 7.8',
  key: 'M15 7a4 4 0 1 1-3.5 6L5 19l-2-2 1.5-1.5L3 14l2-2 1.5 1.5L9 11a4 4 0 0 1 6-4z',
  log: 'M8 6h13 M8 12h13 M8 18h13 M3 6h.01 M3 12h.01 M3 18h.01',
  logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9',
  badge: 'M3 5h18v14H3z M9 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5 M14 10h4 M14 14h3',
} as const;

export function Icon({ d, size = 24, color = 'currentColor', stroke = 2 }: { d: string; size?: number; color?: string; stroke?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

/** Bandeau du haut commun à tous les écrans. */
export function TopBar({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  const { setUser } = useAuth();
  const nav = useNavigate();
  return (
    <header className="topbar">
      <HovisLogo size={36} tone="light" />
      <span className="sep hide-mobile" />
      <span className="topbar-heading">
        <span className="cond topbar-title">{title}</span>
        {sub && <span className="sub hide-mobile">{sub}</span>}
      </span>
      <span style={{ flex: 1 }} />
      <span className="topbar-right">{right}</span>
      <button className="topbar-icon" aria-label="Se déconnecter" title="Se déconnecter" onClick={() => { setUser(null); nav('/'); }}>
        <Icon d={ICONS.logout} size={20} />
      </button>
    </header>
  );
}

export function Clock({ iso }: { iso: string }) {
  const t = new Date(iso);
  const hh = String(t.getHours()).padStart(2, '0');
  const mm = String(t.getMinutes()).padStart(2, '0');
  return <span className="cond clock" style={{ fontWeight: 600, fontSize: 24, fontVariantNumeric: 'tabular-nums' }}>{hh}:{mm}</span>;
}

export const fmt = (n: number) => n.toLocaleString('fr-FR');

/** « En retard de 20 pièces » / « En avance de 7 pièces » : jamais de +7 / −20 nus. */
export function deltaText(d: number, short = false) {
  if (d === 0) return 'Dans les temps';
  if (short) return d < 0 ? `${fmt(-d)} de retard` : `${fmt(d)} d’avance`;
  return d < 0 ? `En retard de ${fmt(-d)} pièces` : `En avance de ${fmt(d)} pièces`;
}

export function DeltaPill({ d }: { d: number }) {
  return <span className={`pill ${d < 0 ? 'pill-red' : 'pill-green'}`} style={{ fontSize: 14, padding: '6px 12px', borderRadius: 14 }}>{deltaText(d)}</span>;
}

export function CountBadge({ n, hot }: { n: number; hot?: boolean }) {
  if (!n) return null;
  return <span className="badge" style={{ background: hot ? 'var(--red)' : 'var(--muted)' }}>{n}</span>;
}

export function Kpi({ label, value, sub, valueStyle }: { label: string; value: ReactNode; sub?: ReactNode; valueStyle?: CSSProperties }) {
  return (
    <div className="card" style={{ padding: '14px 18px', borderRadius: 18, height: '100%' }}>
      <div style={{ fontSize: 14, fontWeight: 600 }} className="muted">{label}</div>
      <div className="num" style={{ fontSize: 38, margin: '4px 0', ...valueStyle }}>{value}</div>
      {sub && <div style={{ fontSize: 13 }} className="muted">{sub}</div>}
    </div>
  );
}

export function Loading() {
  return <div style={{ padding: 40 }} className="muted">Chargement…</div>;
}
