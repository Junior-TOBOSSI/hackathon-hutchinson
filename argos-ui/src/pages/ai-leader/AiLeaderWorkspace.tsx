import { useState } from 'react';
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
  // Docked side menu, OPEN by default; only the menu button opens / closes it (remembered).
  const [menuOpen, setMenuOpen] = useState(() => localStorage.getItem('hovis.aiLeaderMenu') !== 'closed');
  const toggleMenu = () => setMenuOpen((open) => {
    localStorage.setItem('hovis.aiLeaderMenu', open ? 'closed' : 'open');
    return !open;
  });

  const connection = health.error
    ? <span className="pill pill-solid-red" title={health.error}>Databricks indisponible</span>
    : health.data ? <span className="pill pill-green">Databricks connecté</span> : <span className="pill pill-blue">Connexion…</span>;

  return (
    <div className="screen" style={{ background: 'var(--app-bg)' }}>
      <TopBar title="Centre de pilotage IA" sub="AI Leader" right={connection} />
      <nav className="aw-bar" aria-label="Navigation AI Leader">
        <button className="aw-burger" aria-label={menuOpen ? 'Replier le menu' : 'Déplier le menu'} title={menuOpen ? 'Replier le menu' : 'Déplier le menu'}
          aria-expanded={menuOpen} aria-controls="aw-menu" onClick={toggleMenu}>
          <span /><span /><span />
        </button>
        <span className="aw-current">{policies ? 'Réentraînement' : SECTIONS.find((s) => s.id === section)?.label}</span>
        <span style={{ flex: 1 }} />
        {scoped && <ModelPicker />}
        <FreshnessLabel f={freshness} />
        <button className="btn btn-ghost" style={{ height: 38, whiteSpace: 'nowrap' }} disabled={freshness.refreshing > 0}
          title="Relit dans Databricks les données affichées (les autres sections seront relues à leur ouverture)"
          onClick={() => store.refresh()}>
          <span className="row" style={{ gap: 6 }}><Icon d={ICONS.overview} size={16} />Actualiser</span>
        </button>
      </nav>
      <div className="aw-body">
      {menuOpen && <SideMenu section={section} policies={policies}
        onGo={(target) => { if (target === 'policies') setParams(new URLSearchParams({ section: 'training', view: 'policies' })); else go(target, target === 'registry' ? null : undefined); }} />}
      <main className="col aw-main" style={{ padding: '20px clamp(14px, 1.6vw, 28px) 40px', gap: 18, maxWidth: 2400, boxSizing: 'border-box' }}>
        {message && <div className="row between"><span className="muted" style={{ fontWeight: 600 }}>{message}</span><button className="btn" style={{ background: 'none', height: 'auto', padding: 0 }} onClick={() => setMessage('')}>×</button></div>}
        {section === 'overview' && <Overview />}
        {section === 'datasets' && <Datasets />}
        {section === 'training' && <Training onMessage={setMessage} />}
        {section === 'registry' && <Registry onMessage={setMessage} />}
        {section === 'deployment' && <Deployment />}
        {section === 'monitoring' && <Monitoring />}
      </main>
      </div>
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

/** Menu icons (24 px stroke paths, Lucide-style). */
const MENU_ICONS: Record<Section | 'policies', string> = {
  overview: ICONS.overview, // four squares
  datasets: ICONS.db, // database cylinder
  training: 'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18z M10 8.5v7l6-3.5z', // play in a circle
  policies: 'M20 11a8 8 0 0 0-14.6-4.4 M5 3v4h4 M4 13a8 8 0 0 0 14.6 4.4 M19 21v-4h-4', // circular arrows
  registry: 'M12 3l9 4.5-9 4.5-9-4.5z M3 12l9 4.5 9-4.5 M3 16.5l9 4.5 9-4.5', // layers
  deployment: 'M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2.1-.1-2.9a2.2 2.2 0 0 0-2.9-.1z M12 15l-3-3a22 22 0 0 1 2-4A13 13 0 0 1 22 2c0 2.7-.8 7.5-6 11a22 22 0 0 1-4 2z M9 12H4s.6-3 2-4c1.6-1 5 0 5 0 M12 15v5s3-.6 4-2c1-1.6 0-5 0-5', // rocket
  monitoring: 'M3 3h18v18H3z M7 15l3-3 3 2 4-5', // chart in a square
};

/** Menu latéral docké (ouvert par défaut) : sections AI Leader + Politiques sous Training
    Factory. Il ne se ferme que par le bouton « trois traits » de la barre. */
function SideMenu({ section, policies, onGo }: { section: Section; policies: boolean; onGo: (s: Section | 'policies') => void }) {
  const item = (id: Section | 'policies', label: string, icon: Section | 'policies', active: boolean, sub = false) => (
    <button key={id} className={`aw-item${active ? ' active' : ''}${sub ? ' sub' : ''}`}
      aria-current={active ? 'page' : undefined} onClick={() => onGo(id)}>
      <Icon d={MENU_ICONS[icon]} size={sub ? 15 : 17} /><span>{label}</span>
    </button>
  );
  return (
    <nav id="aw-menu" className="aw-side" aria-label="Sections AI Leader">
      {SECTIONS.map((s) => [
        item(s.id, s.label, s.id, s.id === section && !policies),
        s.id === 'training' ? item('policies', 'Réentraînement', 'policies', policies, true) : null,
      ])}
    </nav>
  );
}
