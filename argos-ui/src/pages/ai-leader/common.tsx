import type { CSSProperties, ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';

/* Briques visuelles de l'espace AI Leader, construites sur le thème HOVIS existant
   (classes card / pill / btn / muted / h2 et variables de couleur). */

export type Section = 'overview' | 'datasets' | 'training' | 'registry' | 'deployment' | 'monitoring';

export const SECTIONS: { id: Section; label: string; scoped: boolean }[] = [
  { id: 'overview', label: "Vue d'ensemble", scoped: false },
  { id: 'datasets', label: 'Datasets', scoped: true },
  { id: 'training', label: 'Training Factory', scoped: true },
  { id: 'registry', label: 'Model Registry', scoped: true },
  { id: 'deployment', label: 'Deployment Center', scoped: false },
  { id: 'monitoring', label: 'Monitoring', scoped: true },
];

/** Section et modèle courants, portés par l'URL (?section=…&model=…). */
export function useNav() {
  const [params, setParams] = useSearchParams();
  const section = (SECTIONS.find((s) => s.id === params.get('section'))?.id ?? 'overview') as Section;
  const model = params.get('model');
  const go = (next: Section, nextModel?: string | null) => {
    const p = new URLSearchParams();
    p.set('section', next);
    const m = nextModel === undefined ? model : nextModel;
    if (m) p.set('model', m);
    setParams(p);
    window.scrollTo({ top: 0 });
  };
  return { section, model, go };
}

export const grid = (min = 240): CSSProperties => ({ display: 'grid', gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))`, gap: 16 });

export function Panel({ title, sub, right, children, style }: { title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; style?: CSSProperties }) {
  return (
    <section className="card col" style={{ gap: 14, minWidth: 0, ...style }}>
      {(title || right) && (
        <div className="between" style={{ flexWrap: 'wrap' }}>
          <div className="col" style={{ gap: 2 }}>{title && <h2 className="h2" style={{ fontSize: 21 }}>{title}</h2>}{sub && <span className="muted" style={{ fontSize: 14 }}>{sub}</span>}</div>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint, tone, onClick }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'green' | 'red' | 'amber' | 'muted'; onClick?: () => void }) {
  const color = tone === 'green' ? 'var(--green-text)' : tone === 'red' ? 'var(--red-text)' : tone === 'amber' ? 'var(--amber-text)' : tone === 'muted' ? 'var(--muted)' : 'var(--ink)';
  const body = (
    <>
      <span className="muted" style={{ fontSize: 14, fontWeight: 600 }}>{label}</span>
      <span className="num" style={{ fontSize: 34, color }}>{value}</span>
      {hint && <span className="muted" style={{ fontSize: 13 }}>{hint}</span>}
    </>
  );
  const style: CSSProperties = { padding: '16px 18px', borderRadius: 18, textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 };
  return onClick
    ? <button className="card" onClick={onClick} style={{ ...style, border: '2px solid transparent', cursor: 'pointer' }} title="Ouvrir la section">{body}</button>
    : <div className="card" style={style}>{body}</div>;
}

export function Badge({ tone, children, title }: { tone: 'green' | 'red' | 'amber' | 'blue' | 'grey'; children: ReactNode; title?: string }) {
  const cls = tone === 'grey' ? '' : `pill-${tone}`;
  return <span className={`pill ${cls}`} title={title} style={tone === 'grey' ? { background: 'var(--track)', color: 'var(--muted)' } : undefined}>{children}</span>;
}

export function Loading({ what = 'Chargement' }: { what?: string }) {
  return <div className="muted" style={{ padding: '8px 0' }}>{what}…</div>;
}

export function Unavailable({ children, tone = 'amber' }: { children: ReactNode; tone?: 'amber' | 'red' | 'grey' }) {
  const style: CSSProperties = tone === 'red'
    ? { background: 'var(--red-soft)', color: 'var(--red-dark)' }
    : tone === 'grey' ? { background: 'var(--surface-soft)', color: 'var(--muted)', border: '1px dashed var(--line-strong)' }
      : { background: 'var(--amber-soft)', color: 'var(--amber-text)' };
  return <div style={{ padding: '12px 14px', borderRadius: 14, fontSize: 14, fontWeight: 600, ...style }}>{children}</div>;
}

/** Bloc technique replié par défaut (identifiants, URI, tags…). */
export function Technical({ title = 'Détails techniques', children }: { title?: string; children: ReactNode }) {
  return (
    <details style={{ fontSize: 13 }}>
      <summary className="muted" style={{ cursor: 'pointer', fontWeight: 600 }}>{title}</summary>
      <div className="col" style={{ gap: 4, marginTop: 8, padding: '10px 12px', background: 'var(--surface-soft)', borderRadius: 12, overflowWrap: 'anywhere' }}>{children}</div>
    </details>
  );
}

export function KV({ k, v }: { k: string; v: ReactNode }) {
  return <div><span className="muted">{k} : </span><code style={{ fontSize: 12 }}>{v}</code></div>;
}

export function LinkButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return <button className="btn" onClick={onClick} style={{ background: 'none', color: 'var(--primary)', padding: 0, height: 'auto', textDecoration: 'underline' }}>{children}</button>;
}
