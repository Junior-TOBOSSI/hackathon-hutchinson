import { useState } from 'react';
import { mlops, type RunSummary, type VersionStatus } from '../../api/mlops';
import { GroupedBars } from './charts';
import { Badge, grid, KV, LinkButton, Loading, Panel, Technical, Unavailable, useNav } from './common';
import { errText, useRun, useRunMap, useStore } from './data';
import { dateTime, describe, format, groupBySplit, SPLIT_LABEL, type Split } from './metrics';
import { useSelection, versionRoles } from './selection';

const VERSION_COLORS = ['var(--navy)', 'var(--primary-light)', 'var(--cat-qualite)', 'var(--cat-rythme)'];

export default function Registry({ onMessage }: { onMessage: (m: string) => void }) {
  const { model, status, loading, error } = useSelection();
  if (error) return <Unavailable tone="red">Registre indisponible : {error}</Unavailable>;
  if (loading || !model) return <Loading />;
  if (!status) return <Unavailable tone="grey">Aucune information de registre pour ce modèle.</Unavailable>;
  const { served, champion } = versionRoles(status);

  return (
    <>
      <Panel title={model.display_name} sub={`${model.uc_name} · Unity Catalog`} right={model.synthetic ? <Badge tone="amber">Démo synthétique — pas un modèle industriel</Badge> : undefined}>
        <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
          <Badge tone="green">Approuvée = décision humaine</Badge>
          <Badge tone="blue">Champion = alias du registre (v{champion ?? '—'})</Badge>
          <Badge tone="amber">Servie = exécutée par l'endpoint (v{served ?? '—'})</Badge>
        </div>
        <div className="muted" style={{ fontSize: 14 }}>
          Les métriques ci-dessous sont des mesures <b>hors ligne</b> (validation, test) sur le dataset d'entraînement. Elles ne mesurent pas la performance actuelle en production.
        </div>
      </Panel>
      <div style={grid(360)}>
        {status.versions.map((vs, i) => <VersionCard key={vs.version.version} vs={vs} color={VERSION_COLORS[i % VERSION_COLORS.length]} modelId={model.id} onMessage={onMessage} />)}
      </div>
      {status.versions.length >= 2 && <Comparison versions={status.versions} />}
    </>
  );
}

function VersionCard({ vs, color, modelId, onMessage }: { vs: VersionStatus; color: string; modelId: string; onMessage: (m: string) => void }) {
  const { go } = useNav();
  const store = useStore();
  const run = useRun(vs.version.run_id);
  const [busy, setBusy] = useState(false);
  const v = vs.version;
  const isChampion = vs.aliases.includes('champion');
  const dataset = run.data?.params.dataset_version ?? v.tags.argos_dataset_version ?? null;

  const act = async (label: string, question: string, action: () => Promise<unknown>) => {
    if (!window.confirm(question)) return;
    setBusy(true);
    try {
      await action();
      onMessage(`${label} : confirmé par le registre Unity Catalog.`);
      store.invalidate('statuses', 'overview');
    } catch (e) {
      onMessage(`${label} : refusé (${errText(e)}).`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card col" style={{ gap: 12, borderTop: `6px solid ${color}` }}>
      <div className="between" style={{ flexWrap: 'wrap' }}>
        <span className="num" style={{ fontSize: 30 }}>v{v.version}</span>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          {vs.approved ? <Badge tone="green">approuvée</Badge> : <Badge tone="grey">non approuvée</Badge>}
          {vs.aliases.map((a) => <Badge key={a} tone="blue">{a}</Badge>)}
          {vs.served_by.length ? <Badge tone="amber">servie</Badge> : <Badge tone="grey">non servie</Badge>}
        </div>
      </div>
      <div className="col" style={{ gap: 2, fontSize: 14 }}>
        <span>Entraînée le <b>{dateTime(run.data?.start_time ?? v.created_at)}</b>{run.data?.run_name ? ` · run ${run.data.run_name}` : ''}</span>
        <span>Dataset <b>{dataset ?? 'non renseigné'}</b> {dataset && <LinkButton onClick={() => go('datasets', modelId)}>voir</LinkButton>}</span>
      </div>
      {run.loading && <Loading what="Métriques" />}
      {run.error && <Unavailable tone="red">Métriques indisponibles : {run.error}</Unavailable>}
      {run.data && <MetricsBlock run={run.data} />}
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {!vs.approved && (
          <button className="btn btn-ghost" disabled={busy} onClick={() => act(`Approbation v${v.version}`,
            `Approuver la version ${v.version} ?\n\nAjoute seulement le tag d'approbation dans Unity Catalog. Aucun alias n'est déplacé, rien n'est déployé.`,
            () => mlops.approve(modelId, v.version))}>Approuver</button>
        )}
        {!isChampion && (
          <button className="btn btn-dark" disabled={busy} onClick={() => act(`Alias champion → v${v.version}`,
            `Définir la version ${v.version} comme champion ?\n\nPromotion dans le registre uniquement : la version servie par l'endpoint NE CHANGE PAS et aucun déploiement n'est déclenché.`,
            () => mlops.promote(modelId, v.version))}>Définir comme champion</button>
        )}
        {isChampion && !vs.served_by.length && <span className="muted" style={{ fontSize: 13 }}>Champion non servi : déploiement non disponible (chantier suivant).</span>}
      </div>
      <Technical>
        <KV k="Run MLflow" v={v.run_id ?? '—'} />
        <KV k="Logged model" v={v.model_id ?? '—'} />
        <KV k="Source" v={v.source} />
        <KV k="Statut UC" v={v.status} />
        {Object.entries(v.tags).map(([k, val]) => <KV key={k} k={`tag ${k}`} v={val} />)}
        {run.data && Object.entries(run.data.params).map(([k, val]) => <KV key={k} k={`param ${k}`} v={val} />)}
      </Technical>
    </section>
  );
}

/** Métriques disponibles du run, groupées par nature (jamais de valeur inventée). */
export function MetricsBlock({ run, compact }: { run: RunSummary; compact?: boolean }) {
  const groups = groupBySplit(run.metrics);
  if (!groups.length) return <span className="muted">Aucune métrique enregistrée.</span>;
  return (
    <div className="col" style={{ gap: 10 }}>
      {groups.filter((g) => !compact || g.split === 'validation' || g.split === 'test').map((g) => (
        <div key={g.split} className="col" style={{ gap: 4 }}>
          <span className="muted" style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase' }}>{SPLIT_LABEL[g.split]}</span>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 6 }}>
            {g.items.map(({ info, value }) => (
              <div key={info.key} title={info.key} style={{ padding: '6px 10px', borderRadius: 10, background: 'var(--surface-soft)' }}>
                <div className="muted" style={{ fontSize: 12 }}>{info.label}</div>
                <div className="num" style={{ fontSize: 20 }}>{format(info, value)}</div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Comparaison des versions sur un même split, pour les métriques exprimées en %. */
function Comparison({ versions }: { versions: VersionStatus[] }) {
  const [split, setSplit] = useState<Split>('validation');
  const ids = versions.map((vs) => vs.version.run_id).filter((x): x is string => !!x);
  const runMap = useRunMap(ids);
  if (runMap.error) return <Panel title="Comparer les versions"><Unavailable tone="red">{runMap.error}</Unavailable></Panel>;
  if (!runMap.data) return <Panel title="Comparer les versions"><Loading /></Panel>;
  const byId = runMap.data;
  const runs = versions.map((vs) => ({ vs, run: { data: vs.version.run_id ? byId[vs.version.run_id] : undefined } }));
  const datasets = new Set(runs.map((r) => r.run.data?.params.dataset_version ?? '?'));
  const keys = [...new Set(runs.flatMap((r) => Object.keys(r.run.data?.metrics ?? {})))]
    .map(describe).filter((m) => m.split === split && m.kind === 'ratio');
  const groups = keys.map((info) => ({
    label: info.label,
    bars: runs.filter((r) => r.run.data?.metrics[info.key] != null).map((r, i) => ({
      label: `v${r.vs.version.version}`, value: r.run.data?.metrics[info.key] as number, color: VERSION_COLORS[i % VERSION_COLORS.length],
    })),
  }));
  return (
    <Panel title="Comparer les versions" sub="Mesures hors ligne en pourcentage, par version"
      right={<div className="row" style={{ gap: 0, border: '2px solid var(--line)', borderRadius: 22, padding: 3 }}>
        {(['validation', 'test'] as Split[]).map((s) => (
          <button key={s} className="btn" onClick={() => setSplit(s)} style={{ height: 34, borderRadius: 18, background: split === s ? 'var(--navy)' : 'transparent', color: split === s ? '#fff' : 'var(--muted)' }}>{s === 'validation' ? 'Validation' : 'Test'}</button>
        ))}
      </div>}>
      {datasets.size > 1 || datasets.has('?')
        ? <Unavailable>Attention : les versions n'ont pas été évaluées sur le même dataset ({[...datasets].join(', ')}). La comparaison directe n'est pas valable.</Unavailable>
        : <span className="muted" style={{ fontSize: 14 }}>Même dataset ({[...datasets][0]}) et même protocole : comparaison valable.</span>}
      {groups.length === 0
        ? <Unavailable tone="grey">Aucune métrique en pourcentage commune sur ce split.</Unavailable>
        : <GroupedBars groups={groups} max={1} format={(x) => format(describe('val_accuracy'), x)}
            legend={runs.map((r, i) => ({ label: `v${r.vs.version.version}`, color: VERSION_COLORS[i % VERSION_COLORS.length] }))} />}
    </Panel>
  );
}
