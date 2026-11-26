import { useState } from 'react';
import { Icon, ICONS, TopBar } from '../../components/ui';
import { SECTIONS, useNav } from './common';
import { MlopsDataProvider, useFreshness, useHealth, useStore } from './data';
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
  const freshness = useFreshness();
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
          <FreshnessLabel f={freshness} />
          <button className="btn btn-ghost" style={{ height: 38, whiteSpace: 'nowrap' }} disabled={freshness.refreshing > 0}
            title="Relit dans Databricks les données affichées (les autres sections seront relues à leur ouverture)"
            onClick={() => store.refresh()}>
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

const time = (iso: string) => new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

/** Freshness of the DISPLAYED resources: a range when their read times differ, the origin
    (live read / server cache / last known value) and what is still loading. */
function FreshnessLabel({ f }: { f: ReturnType<typeof useFreshness> }) {
  const parts: string[] = [];
  if (f.oldest && f.newest) {
    parts.push(time(f.oldest) === time(f.newest) ? `Lu à ${time(f.oldest)}` : `Lu entre ${time(f.oldest)} et ${time(f.newest)}`);
    if (f.kinds.includes('stale')) parts.push('dernier résultat connu');
    else if (f.kinds.some((k) => k === 'hit' || k === 'mixed')) parts.push(f.kinds.includes('miss') ? 'en partie depuis le cache serveur' : 'cache serveur');
    else parts.push('lecture directe');
  }
  if (f.refreshing) parts.push(`actualisation… (${f.refreshing})`);
  else if (f.loading) parts.push(`chargement… (${f.loading})`);
  if (f.staleAfterError) parts.push(`${f.staleAfterError} en échec : dernier résultat affiché`);
  if (!parts.length) return null;
  return <span className="muted" style={{ fontSize: 13, whiteSpace: 'nowrap' }} title="Date réelle de lecture dans Databricks des données affichées à l'écran">{parts.join(' · ')}</span>;
}
