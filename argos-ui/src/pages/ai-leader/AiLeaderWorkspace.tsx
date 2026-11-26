import { useState } from 'react';
import { Icon, ICONS, TopBar } from '../../components/ui';
import { SECTIONS, useNav } from './common';
import { MlopsDataProvider, useHealth, useStore } from './data';
import Datasets from './Datasets';
import Deployment from './Deployment';
import Monitoring from './Monitoring';
import Overview from './Overview';
import Registry from './Registry';
import { PENDING_SLOTS, useSelection } from './selection';
import Training from './Training';

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
  const [message, setMessage] = useState('');
  const scoped = SECTIONS.find((s) => s.id === section)?.scoped ?? false;

  const connection = health.error
    ? <span className="pill pill-solid-red" title={health.error}>Databricks indisponible</span>
    : health.data ? <span className="pill pill-green">Databricks connecté</span> : <span className="pill pill-blue">Connexion…</span>;

  return (
    <div className="screen" style={{ background: 'var(--app-bg)' }}>
      <TopBar title="Fabrique de modèles" sub="AI Leader · données réelles Databricks" right={connection} />
      <nav style={{ background: '#fff', borderBottom: '1px solid var(--line)', position: 'sticky', top: 0, zIndex: 20 }}>
        <div className="row" style={{ padding: '0 24px', gap: 4, overflowX: 'auto', flexWrap: 'nowrap' }}>
          {SECTIONS.map((s) => {
            const active = s.id === section;
            return (
              <button key={s.id} onClick={() => go(s.id)} className="btn" aria-current={active ? 'page' : undefined}
                style={{ background: 'none', borderRadius: 0, height: 52, whiteSpace: 'nowrap', color: active ? 'var(--ink)' : 'var(--muted)', borderBottom: `3px solid ${active ? 'var(--red)' : 'transparent'}` }}>
                {s.label}
              </button>
            );
          })}
          <span style={{ flex: 1 }} />
          {scoped && <ModelPicker />}
          <button className="btn btn-ghost" style={{ height: 38, whiteSpace: 'nowrap' }} onClick={() => { store.refresh(); setMessage('Données rechargées depuis Databricks.'); }}>
            <span className="row" style={{ gap: 6 }}><Icon d={ICONS.overview} size={16} />Actualiser</span>
          </button>
        </div>
      </nav>
      <main className="col" style={{ padding: '20px 24px 40px', gap: 18, width: '100%', maxWidth: 1360, margin: '0 auto', boxSizing: 'border-box' }}>
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
