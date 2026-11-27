import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Icon, ICONS, TopBar } from '../../components/ui';
import { SECTIONS, useNav, type Section } from './common';
import { MlopsDataProvider, useFreshness, useHealth, useStore } from './data';
import Datasets from './Datasets';
import Deployment from './Deployment';
import Monitoring from './Monitoring';
import Overview from './Overview';
import Registry from './Registry';
import { PENDING_SLOTS, useSelection } from './selection';
import Training from './Training';
import './workspace.css';

/** Espace de travail AI Leader (données réelles Databricks via le backend ARGOS). */
export default function AiLeaderWorkspace() {
  return (
    <MlopsDataProvider>
      <Workspace />
    </MlopsDataProvider>
  );
}

function Workspace() {
  const { section, go } = useNav();
  const health = useHealth();
  const store = useStore();
  const freshness = useFreshness();
  const [message, setMessage] = useState('');
  const scoped = SECTIONS.find((s) => s.id === section)?.scoped ?? false;
  const [params, setParams] = useSearchParams();
  const policies = section === 'training' && params.get('view') === 'policies';
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const closeMenu = () => { setMenuOpen(false); menuButton.current?.focus(); };

  const connection = health.error
    ? <span className="pill pill-solid-red" title={health.error}>Databricks indisponible</span>
    : health.data ? <span className="pill pill-green">Databricks connecté</span> : <span className="pill pill-blue">Connexion…</span>;

  return (
    <div className="screen" style={{ background: 'var(--app-bg)' }}>
      <TopBar title="Fabrique de modèles" sub="AI Leader" right={connection} />
      <nav className="aw-bar" aria-label="Navigation AI Leader">
        <button ref={menuButton} className="aw-burger" aria-label="Ouvrir le menu" aria-expanded={menuOpen} aria-controls="aw-menu" onClick={() => setMenuOpen(true)}>
          <span /><span /><span />
        </button>
        <span className="aw-current">{policies ? 'Politiques de réentraînement' : SECTIONS.find((s) => s.id === section)?.label}</span>
        <span style={{ flex: 1 }} />
        {scoped && <ModelPicker />}
        <FreshnessLabel f={freshness} />
        <button className="btn btn-ghost" style={{ height: 38, whiteSpace: 'nowrap' }} disabled={freshness.refreshing > 0}
          title="Relit dans Databricks les données affichées (les autres sections seront relues à leur ouverture)"
          onClick={() => store.refresh()}>
          <span className="row" style={{ gap: 6 }}><Icon d={ICONS.overview} size={16} />Actualiser</span>
        </button>
      </nav>
      {menuOpen && <SideMenu section={section} policies={policies} onClose={closeMenu}
        onGo={(target) => { closeMenu(); if (target === 'policies') setParams(new URLSearchParams({ section: 'training', view: 'policies' })); else go(target, target === 'registry' ? null : undefined); }} />}
      <main className="col" style={{ padding: '20px clamp(14px, 1.6vw, 28px) 40px', gap: 18, width: '100%', maxWidth: 2400, margin: '0 auto', boxSizing: 'border-box' }}>
        {message && <div className="row between"><span className="muted" style={{ fontWeight: 600 }}>{message}</span><button className="btn" style={{ background: 'none', height: 'auto', padding: 0 }} onClick={() => setMessage('')}>×</button></div>}
        {section === 'overview' && <Overview />}
        {section === 'datasets' && <Datasets />}
        {section === 'training' && <Training onMessage={setMessage} />}
        {section === 'registry' && <Registry onMessage={setMessage} />}
        {section === 'deployment' && <Deployment />}
        {section === 'monitoring' && <Monitoring />}
      </main>
    </div>
  );
}

function ModelPicker() {
  const { section, go } = useNav();
  const { models, model } = useSelection();
  if (!models.length) return null;
  return (
    <label className="row" style={{ gap: 8, fontSize: 14, whiteSpace: 'nowrap' }}>
      <span className="muted" style={{ fontWeight: 600 }}>Modèle</span>
      <select value={model?.id ?? ''} onChange={(e) => go(section, e.target.value)}
        style={{ height: 38, borderRadius: 10, border: '2px solid var(--line-strong)', padding: '0 10px', fontSize: 14, fontFamily: 'inherit', background: '#fff' }}>
        {models.map((m) => <option key={m.id} value={m.id}>{m.display_name}</option>)}
        {PENDING_SLOTS.map((s) => <option key={s.name} disabled>{s.name} — en attente de livraison</option>)}
      </select>
    </label>
  );
}

const time = (iso: string) => new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

/** Freshness of the DISPLAYED resources: a range when their read times differ, the origin
    (live read / server cache / last known value) and what is still loading. */
function FreshnessLabel({ f }: { f: ReturnType<typeof useFreshness> }) {
  const parts: string[] = [];
  if (f.oldest && f.newest) {
    parts.push(time(f.oldest) === time(f.newest) ? `Lu à ${time(f.oldest)}` : `Lu entre ${time(f.oldest)} et ${time(f.newest)}`);
    if (f.kinds.includes('stale')) parts.push('dernier résultat connu');
  }
  if (f.refreshing) parts.push(`actualisation… (${f.refreshing})`);
  else if (f.loading) parts.push(`chargement… (${f.loading})`);
  if (f.staleAfterError) parts.push(`${f.staleAfterError} en échec : dernier résultat affiché`);
  if (!parts.length) return null;
  return <span className="muted" style={{ fontSize: 13, whiteSpace: 'nowrap' }} title="Date réelle de lecture dans Databricks des données affichées à l'écran">{parts.join(' · ')}</span>;
}

const MENU_ICONS: Record<Section, keyof typeof ICONS> = {
  overview: 'home', datasets: 'db', training: 'play', registry: 'badge', deployment: 'monitor', monitoring: 'bars',
};

/** Menu latéral déployable : sections AI Leader (+ Politiques sous Training Factory).
    Se ferme avec Échap, un clic à l'extérieur ou après une sélection. */
function SideMenu({ section, policies, onClose, onGo }: { section: Section; policies: boolean; onClose: () => void; onGo: (s: Section | 'policies') => void }) {
  const first = useRef<HTMLButtonElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    first.current?.focus(); // once, at opening (not at every data refresh)
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close.current(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  const item = (id: Section | 'policies', label: string, icon: keyof typeof ICONS, active: boolean, sub = false) => (
    <button key={id} ref={id === 'overview' ? first : undefined} className={`aw-item${active ? ' active' : ''}${sub ? ' sub' : ''}`}
      aria-current={active ? 'page' : undefined} onClick={() => onGo(id)}>
      <Icon d={ICONS[icon]} size={sub ? 16 : 19} /><span>{label}</span>
    </button>
  );
  return (
    <div className="aw-layer" role="presentation" onClick={onClose}>
      <aside id="aw-menu" className="aw-menu" role="dialog" aria-modal="true" aria-label="Menu AI Leader" onClick={(e) => e.stopPropagation()}>
        <div className="aw-menu-head">
          <span>AI Leader</span>
          <button className="aw-close" aria-label="Fermer le menu" onClick={onClose}>×</button>
        </div>
        {SECTIONS.map((s) => [
          item(s.id, s.label, MENU_ICONS[s.id], s.id === section && !policies),
          s.id === 'training' ? item('policies', 'Politiques de réentraînement', 'log', policies, true) : null,
        ])}
      </aside>
    </div>
  );
}
