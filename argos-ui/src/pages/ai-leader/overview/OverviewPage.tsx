import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Icon, ICONS } from '../../../components/ui';
import {
  overview, type ActivityData, type Block, type BlockName, type DatasetsData, type InfrastructureData, type MonitoringData,
  type RegistryData, type RetrainingData, type TrainingData,
} from '../../../api/overview';
import { Loading, Unavailable } from '../common';
import { read, useResource, type Resource } from '../data';
import '../training/training.css';
import { Chip, SelectField, type IconName } from '../ui';
import { bucketRuns, frReason, RUN_GROUPS } from './history';
import './overview.css';

/* Accueil AI Leader (DBX-09). Chaque bloc est chargé séparément depuis /api/mlops/overview/v2
   (agrégation légère, caches partagés) : une source lente ou indisponible ne bloque jamais
   le reste. Aucun chiffre, aucun nom de modèle et aucune série n'est codé en dur. */

const useBlock = <T,>(name: BlockName) => useResource(`ov:${name}`, read((o) => overview.block<T>(name, o)));
const USE_CASE: Record<string, string> = { quality: 'Qualité', safety: 'Sécurité (EPI)', workstation: 'Poste de travail / 5S' };
const uc = (u: string | null | undefined) => (u ? USE_CASE[u] ?? u : '—');
const dt = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '—');
const time = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : '—');
const n = (v: number | null | undefined) => (v == null ? '—' : v.toLocaleString('fr-FR'));

/** Navigation vers les écrans existants (aucune deuxième implémentation). */
function useGoto() {
  const [, setParams] = useSearchParams();
  return (params: Record<string, string | null | undefined>) => {
    const next = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v) next.set(k, v);
    setParams(next);
    window.scrollTo({ top: 0 });
  };
}

function BlockState<T>({ res, children, label }: { res: Resource<Block<T>>; children: (d: T, b: Block<T>) => ReactNode; label: string }) {
  if (res.loading) return <Loading what={`Lecture ${label}`} />;
  if (res.error) return <Unavailable tone="red">{label} indisponible : {res.error}</Unavailable>;
  const b = res.data;
  if (!b) return null;
  if (b.status === 'unavailable' || !b.data) return <Unavailable tone="red">{label} indisponible{b.detail ? ` : ${b.detail}` : ''}</Unavailable>;
  return <>
    {b.failed.length > 0 && <Unavailable>Données partielles : {b.failed.map((f) => f.source).join(', ')} indisponible(s).</Unavailable>}
    {children(b.data, b)}
  </>;
}

const StatusChip = ({ b }: { b: Block<unknown> | null }) => !b ? null
  : b.status === 'simulated' ? <Chip tone="amber" title="Données issues de la simulation des postes">Simulé</Chip>
    : b.status === 'partial' ? <Chip tone="amber">Partiel</Chip>
      : b.status === 'unavailable' ? <Chip tone="red">Indisponible</Chip> : null;

function Card({ title, icon, sub, res, right, children, className }: {
  title: string; icon: IconName; sub?: ReactNode; res?: Resource<Block<unknown>>; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`card ov-card ${className ?? ''}`}>
      <div className="ov-card-head">
        <span className="ov-card-icon"><Icon d={ICONS[icon]} size={18} /></span>
        <div className="col" style={{ gap: 2, minWidth: 0, flex: 1 }}>
          <h2>{title}</h2>
          {sub && <span className="muted" style={{ fontSize: 13 }}>{sub}</span>}
        </div>
        <span className="row" style={{ gap: 6, alignItems: 'center' }}>
          {res?.data && <StatusChip b={res.data} />}
          {res?.data && <span className="ov-fresh" title="Date de construction du bloc (les sources gardent leur propre cache)">{res.refreshing ? 'actualisation…' : `à ${time(res.data.fetched_at)}`}</span>}
          {right}
        </span>
      </div>
      {children}
    </section>
  );
}

export default function OverviewPage() {
  const goto = useGoto();
  const ds = useBlock<DatasetsData>('datasets');
  const tr = useBlock<TrainingData>('training');
  const rg = useBlock<RegistryData>('registry');
  const inf = useBlock<InfrastructureData>('infrastructure');
  const mon = useBlock<MonitoringData>('monitoring');
  const ret = useBlock<RetrainingData>('retraining');
  const act = useBlock<ActivityData>('activity');
  const v = <T,>(r: Resource<Block<T>>, f: (d: T) => ReactNode) => (r.error ? '—' : r.data?.data ? f(r.data.data) : r.data ? '—' : '…');

  const endpoints = inf.data?.data?.endpoints;
  const ready = endpoints?.filter((e) => e.ready === 'READY').length;

  return (
    <div className="tf">
      <header className="card tf-hero">
        <div className="tf-hero-title">
          <span className="tf-hero-icon"><Icon d={ICONS.overview} size={24} /></span>
          <div><h1 className="h2">Tableau de bord</h1>
            <p className="muted">Pilotez vos modèles de vision industrielle, de la donnée à la production.</p></div>
        </div>
      </header>

      <div className="ov-kpis">
        <OvKpi icon={ICONS.db} label="Jeux de données" value={v(ds, (d) => n(d.families))}
          hint={ds.data?.data ? `${n(ds.data.data.published_versions)} versions · ${ds.data.data.latest_images == null ? 'images inconnues' : `${n(ds.data.data.latest_images)} images`}` : undefined} />
        <OvKpi icon={PLAY_FILLED} label="Entraînements en cours" value={v(tr, (d) => n(d.running))}
          hint={tr.data?.data ? `${n(tr.data.data.by_status.succeeded ?? 0)} réussis · ${n(tr.data.data.by_status.failed ?? 0)} échoués` : undefined} />
        <OvKpi icon={NEURONS} label="Modèles candidats" value={v(rg, (d) => n(d.candidates))} tone={rg.data?.data?.candidates ? 'amber' : undefined}
          hint="En attente de décision" />
        <OvKpi icon={ICONS.shield} label="Modèles approuvés" value={v(rg, (d) => n(d.approved))} tone={rg.data?.data?.approved ? 'green' : undefined}
          hint={rg.data?.data ? `${n(rg.data.data.champions)} modèle${rg.data.data.champions > 1 ? 's' : ''} champion` : undefined} />
        <OvKpi icon={ICONS.monitor} label="Modèles déployés sur Edge" value={v(rg, (d) => {
          const edge = d.models.filter((m) => m.edge_declared.length > 0).length;
          return edge ? n(edge) : '—';
        })}
          hint={endpoints ? `${ready} endpoint${(ready ?? 0) > 1 ? 's' : ''} cloud disponible${(ready ?? 0) > 1 ? 's' : ''}` : undefined} />
      </div>


      <div className="ov-columns">
        <div className="ov-col">
          <Card title="Activité récente" icon="log" sub="Événements réels datés, avec leur provenance" res={act}><Activity res={act} goto={goto} /></Card>
          <Card title="Infrastructure" icon="grid" sub="Connexions et parc industriel" res={inf}><Infrastructure res={inf} /></Card>
          <Card title="Réentraînement" icon="key" res={ret}
            right={<button className="btn btn-ghost ov-link" onClick={() => goto({ section: 'training', view: 'policies' })}>Politiques →</button>}><Retraining res={ret} /></Card>
        </div>
        <div className="ov-col">
          <Card title="Historique des entraînements" icon="bars" sub="Job runs Databricks réels des pipelines déclarés" res={tr}><TrainingHistory res={tr} goto={goto} /></Card>
          <Card title="Monitoring" icon="shieldAlert" sub="Données et scores ; pas d’accuracy de production sans vérité terrain" res={mon}
            right={<button className="btn btn-ghost ov-link" onClick={() => goto({ section: 'monitoring' })}>Ouvrir →</button>}><Monitoring res={mon} /></Card>
          <Card title="Datasets" icon="db" sub="Familles, versions publiées et images" res={ds}
            right={<button className="btn btn-ghost ov-link" onClick={() => goto({ section: 'datasets' })}>Catalogue →</button>}><Datasets res={ds} goto={goto} /></Card>
        </div>
      </div>
      <Card title="État des modèles" icon="badge" sub="Registre Unity Catalog, Serving Databricks et versions déclarées par les postes" res={rg}><Models res={rg} goto={goto} /></Card>
    </div>
  );
}

/* Mockup KPI card: icon on top, label, value, hint (HOVIS colours). */
const NEURONS = 'M5 6a2 2 0 1 0 0 .01 M5 18a2 2 0 1 0 0 .01 M12 4a2 2 0 1 0 0 .01 M12 12a2 2 0 1 0 0 .01 M12 20a2 2 0 1 0 0 .01 M19 9a2 2 0 1 0 0 .01 M19 15a2 2 0 1 0 0 .01 M7 6.5l3 -2 M7 6.5l3 5 M7 17.5l3 -5 M7 17.5l3 2 M14 4.5l3 4 M14 12l3 -2.5 M14 12l3 2.5 M14 19.5l3 -4';
const PLAY_FILLED = 'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18z M10 8.5v7l6-3.5z';

function OvKpi({ icon, label, value, hint, tone }: { icon: string; label: string; value: ReactNode; hint?: string; tone?: 'green' | 'amber' }) {
  return (
    <div className="card ov-kpi">
      <span className="ov-kpi-icon"><Icon d={icon} size={18} /></span>
      <span className="ov-kpi-label">{label}</span>
      <b className={`ov-kpi-value${tone ? ` ${tone}` : ''}`}>{value}</b>
      {hint && <span className="ov-kpi-hint">{hint}</span>}
    </div>
  );
}

/* ------------------------------------------------------------------ activité */

const TYPE: Record<string, [string, IconName]> = {
  dataset: ['Dataset', 'db'], training_started: ['Entraînement', 'play'], training_ended: ['Entraînement', 'play'],
  model_version: ['Version', 'layers'], decision: ['Décision', 'check'], deploy: ['Déploiement', 'monitor'],
  rollback: ['Rollback', 'monitor'], proposal: ['Proposition', 'log'], alert: ['Alerte', 'warn'],
};
const STATUS: Record<string, [string, 'green' | 'red' | 'amber' | 'blue' | 'grey']> = {
  succeeded: ['Réussi', 'green'], failed: ['Échec', 'red'], cancelled: ['Annulé', 'grey'], running: ['En cours', 'blue'], queued: ['En attente', 'blue'],
  started: ['Lancé', 'blue'], published: ['Publiée', 'blue'], registered: ['Enregistrée', 'grey'], applied: ['Appliquée', 'green'], uncertain: ['Incertaine', 'amber'],
  requesting: ['En cours', 'blue'], pending: ['En attente', 'amber'], accepted: ['Acceptée', 'blue'], launched: ['Lancée', 'green'], rejected: ['Refusée', 'grey'],
  open: ['Ouverte', 'red'], resolved: ['Résolue', 'green'], updating: ['En cours', 'blue'], prepared: ['Préparée', 'grey'], expired: ['Expirée', 'grey'],
};

function Activity({ res, goto }: { res: Resource<Block<ActivityData>>; goto: (p: Record<string, string>) => void }) {
  const [all, setAll] = useState(false);
  return <BlockState res={res} label="L’activité">{(d) => {
    const rows = d.events.slice(0, all ? d.events.length : 8);
    if (!rows.length) return <Unavailable tone="grey">Aucun événement daté disponible.</Unavailable>;
    return <>
      <div className="tf-table-wrap"><table className="tf-table ov-table"><thead><tr><th>Date</th><th>Type</th><th>Détail</th><th>Statut</th></tr></thead>
        <tbody>{rows.map((e, i) => {
          const [label, icon] = TYPE[e.type] ?? [e.type, 'log'];
          const [st, tone] = STATUS[e.status] ?? [e.status, 'grey'];
          return (
            <tr key={i} className={e.link ? '' : 'static'} tabIndex={e.link ? 0 : -1} onClick={() => e.link && goto(e.link)} title={e.link ? 'Ouvrir le détail' : undefined}>
              <td style={{ whiteSpace: 'nowrap' }}>{dt(e.at)}</td>
              <td><span className="row" style={{ gap: 6 }}><Icon d={ICONS[icon]} size={15} />{label}</span><small>{e.source}</small></td>
              <td><b>{e.title}</b>{e.detail && <small>{frReason(e.detail)}</small>}</td>
              <td><Chip tone={tone}>{st}</Chip></td>
            </tr>);
        })}</tbody></table></div>
      <div className="between" style={{ fontSize: 13 }}>
        <span className="muted">{d.not_dated.length ? `Non datés : ${d.not_dated.join(' ; ')}` : ''}</span>
        {d.events.length > 8 && <button className="btn btn-ghost ov-link" onClick={() => setAll(!all)}>{all ? 'Réduire' : `Voir tout l’historique (${d.events.length})`}</button>}
      </div>
    </>;
  }}</BlockState>;
}

/* ------------------------------------------------------------------ historique des entraînements */

const RUN_COLORS = RUN_GROUPS;
const PERIODS: [string, string][] = [['14', '14 derniers jours'], ['30', '30 derniers jours'], ['90', '90 derniers jours'], ['all', 'Tout l’historique disponible']];

function TrainingHistory({ res, goto }: { res: Resource<Block<TrainingData>>; goto: (p: Record<string, string>) => void }) {
  const [period, setPeriod] = useState('30');
  return <BlockState res={res} label="L’historique">{(d) => <History d={d} period={period} setPeriod={setPeriod} goto={goto} />}</BlockState>;
}

function History({ d, period, setPeriod, goto }: { d: TrainingData; period: string; setPeriod: (p: string) => void; goto: (p: Record<string, string>) => void }) {
  const { buckets, runs, weekly } = useMemo(() => bucketRuns(d.runs, period), [d.runs, period]);
  const max = Math.max(1, ...buckets.map(([, b]) => Object.values(b).reduce((x, y) => x + y, 0)));
  const box = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(520);
  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const H = 170, bw = Math.min(56, W / Math.max(1, buckets.length) - 12);
  return (
    <div className="col" style={{ gap: 10 }} ref={box}>
      <div className="between" style={{ gap: 8, flexWrap: 'wrap' }}>
        <SelectField label="Période" icon="none" value={period} onChange={setPeriod} options={PERIODS} />
        <span className="muted" style={{ fontSize: 13 }}>{runs.length} run(s) · regroupement {weekly ? 'par semaine' : 'par jour'}</span>
      </div>
      {buckets.length === 0 ? <Unavailable tone="grey">Aucun entraînement sur cette période.</Unavailable> : (
        <svg viewBox={`0 0 ${W} ${H + 24}`} className="ov-chart" role="img" aria-label="Entraînements par période et par statut">
          <line x1="0" x2={W} y1={H} y2={H} className="ov-axis" />
          {buckets.map(([k, b], i) => {
            const x = (i + 0.5) * (W / buckets.length) - bw / 2;
            let y = H;
            return <g key={k}>
              {RUN_COLORS.map(([, label, color]) => {
                const c = b[label] ?? 0;
                if (!c) return null;
                const h = (c / max) * (H - 10);
                y -= h;
                return <rect key={label} x={x} y={y} width={bw} height={h} rx="3" fill={color}><title>{`${k} · ${label} : ${c}`}</title></rect>;
              })}
              <text x={x + bw / 2} y={H + 16} textAnchor="middle" className="ov-tick">{new Date(k).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })}</text>
            </g>;
          })}
        </svg>
      )}
      <div className="row" style={{ gap: 14, flexWrap: 'wrap', fontSize: 13 }}>
        {RUN_COLORS.map(([s, label, color]) => <span key={label} className="row" style={{ gap: 6 }}>
          <span className="hv-dot" style={{ background: color }} />{label} <b>{runs.filter((r) => s.includes(r.status)).length}</b></span>)}
      </div>
      {runs[0] && <button className="ov-last" onClick={() => goto({ section: 'training', run: String(runs[0].job_run_id) })}>
        Dernier : <b>{runs[0].pipeline_id}</b> · {runs[0].dataset_id ?? '?'} {runs[0].dataset_version ?? ''} · {dt(runs[0].started_at)} →</button>}
    </div>
  );
}

/* ------------------------------------------------------------------ modèles */

function Models({ res, goto }: { res: Resource<Block<RegistryData>>; goto: (p: Record<string, string>) => void }) {
  return <BlockState res={res} label="Le registre">{(d) => (
    <div className="col" style={{ gap: 10 }}>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {Object.entries(d.by_use_case).map(([k, c]) => <Chip key={k} tone="blue">{uc(k)} : {c} modèle(s)</Chip>)}
        <Chip tone="grey">{d.versions} version(s)</Chip>
      </div>
      {d.models.length === 0 ? <Unavailable tone="grey">Aucun modèle géré.</Unavailable> : (
        <div className="tf-table-wrap"><table className="tf-table ov-table"><thead><tr>
          <th>Modèle</th><th>Cas d’usage</th><th className="num">Versions</th><th className="num">Candidates</th><th className="num">Approuvées</th>
          <th>Champion</th><th>Servie (Databricks Serving)</th><th>Chargée sur les postes (Edge)</th>
        </tr></thead><tbody>{d.models.map((m) => (
          <tr key={m.model_id} tabIndex={0} onClick={() => goto({ section: 'registry', model: m.model_id })}>
            <td><b>{m.name}</b><small>{m.uc_name}{m.synthetic ? ' · synthétique' : ''}</small></td>
            <td>{uc(m.use_case)}</td>
            <td className="num">{m.versions.length}</td>
            <td className="num">{m.candidates}</td>
            <td className="num">{m.approved}</td>
            <td>{m.champion ? <Chip tone="navy">v{m.champion}</Chip> : <span className="muted">aucun</span>}</td>
            <td>{Object.keys(m.served).length ? Object.entries(m.served).map(([ep, v]) => <Chip key={ep} tone="green" title={ep}>v{v} · {ep}</Chip>) : <span className="muted">non servi</span>}</td>
            <td>{m.edge_declared.length
              ? <span title={m.edge_declared.map((e) => `${e.station_id} : ${e.model_name ?? '?'} ${e.model_version ?? ''}`).join('\n')}>
                {m.edge_declared.length} poste(s){m.edge_declared.some((e) => e.simulated) ? ' (simulés)' : ''}<small>{[...new Set(m.edge_declared.map((e) => `${e.model_name ?? '?'} v${e.model_version ?? '?'}`))].join(', ')} · non relié au registre sans référence de paquet</small></span>
              : <span className="muted">aucune déclaration</span>}</td>
          </tr>))}</tbody></table></div>
      )}
    </div>
  )}</BlockState>;
}

/* ------------------------------------------------------------------ infrastructure */

const CHECK: Record<string, string> = { databricks: 'Connexion Databricks', mlflow: 'MLflow (tracking)', unity_catalog: 'Unity Catalog' };

function Infrastructure({ res }: { res: Resource<Block<InfrastructureData>> }) {
  return <BlockState res={res} label="L’infrastructure">{(d) => (
    <div className="col" style={{ gap: 10 }}>
      <ul className="ov-checks">
        {d.checks.map((c) => <li key={c.name}><span>{CHECK[c.name] ?? c.name}</span>
          {c.status === 'available' ? <Chip tone="green">Disponible</Chip> : <Chip tone="red" title={String(c.detail)}>Indisponible</Chip>}</li>)}
        <li><span>Endpoints Serving</span>{d.endpoints.length
          ? <span className="row" style={{ gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>{d.endpoints.map((e) => <Chip key={e.name} tone={e.ready === 'READY' ? 'green' : 'red'} title={e.served.map(([m, v]) => `${m} v${v}`).join(', ')}>{e.name} · {e.ready ?? 'inconnu'}</Chip>)}</span>
          : <span className="muted">aucun</span>}</li>
        <li><span>Core industriel</span>{d.core.status === 'available' ? <Chip tone="green">Disponible</Chip> : d.core.status === 'partial' ? <Chip tone="amber" title={d.core.detail ?? ''}>Partiel</Chip> : <Chip tone="red" title={d.core.detail ?? ''}>Indisponible</Chip>}</li>
        <li><span>Parc industriel</span><span className="row" style={{ gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <Chip tone="grey">{d.fleet.stations} poste(s)</Chip><Chip tone="green">{d.fleet.online} en ligne</Chip><Chip tone={d.fleet.offline ? 'amber' : 'grey'}>{d.fleet.offline} hors ligne</Chip>
          {d.fleet.simulated > 0 && <Chip tone="amber">{d.fleet.simulated} simulé(s)</Chip>}</span></li>
      </ul>
    </div>
  )}</BlockState>;
}

/* ------------------------------------------------------------------ monitoring et réentraînement */

const Metric = ({ label, value, tone, hint }: { label: string; value: ReactNode; tone?: string; hint?: string }) => (
  <div className="ov-metric" title={hint}><span>{label}</span><b style={tone ? { color: `var(--${tone}-text)` } : undefined}>{value}</b></div>
);

function Monitoring({ res }: { res: Resource<Block<MonitoringData>> }) {
  return <BlockState res={res} label="Le Monitoring">{(d) => (
    <div className="col" style={{ gap: 10 }}>
      {d.data_kind === 'simulated' && <div className="ov-banner">Données simulées : aucune inférence de production réelle n’est encore disponible.</div>}
      <div className="ov-metrics">
        <Metric label="Inférences" value={n(d.inferences)} />
        <Metric label="Latence P95" value={d.latency_p95 == null ? '—' : `${Math.round(d.latency_p95)} ms`} />
        <Metric label="Alertes ouvertes" value={n(d.open_alerts)} tone={d.open_alerts ? 'red' : undefined} />
        <Metric label="Dérives détectées" value={n(d.drift_detected)} tone={d.drift_detected ? 'red' : undefined} />
        <Metric label="Références absentes" value={n(d.reference_absent)} tone={d.reference_absent ? 'amber' : undefined} />
        <Metric label="Couverture insuffisante" value={n(d.insufficient_coverage)} tone={d.insufficient_coverage ? 'amber' : undefined} />
        <Metric label="À investiguer" value={n(d.to_investigate)} tone={d.to_investigate ? 'red' : undefined} />
        <Metric label="Dernière collecte" value={d.last_collection ? dt(d.last_collection) : 'aucune'} />
      </div>
    </div>
  )}</BlockState>;
}

function Retraining({ res }: { res: Resource<Block<RetrainingData>> }) {
  return <BlockState res={res} label="Le réentraînement">{(d) => (
    <div className="col" style={{ gap: 10 }}>
      <div className="ov-metrics">
        <Metric label="Politiques actives" value={n(d.active)} />
        <Metric label="Politiques inactives" value={n(d.inactive)} />
        <Metric label="Propositions en attente" value={n(d.pending_proposals)} tone={d.pending_proposals ? 'amber' : undefined} />
        <Metric label="Conditions satisfaites" value={n(d.satisfied_conditions)} hint="d’après la dernière évaluation explicite de chaque politique" />
        <Metric label="Exécutions automatiques" value={n(d.automatic_launches)} />
        <Metric label="Politiques automatiques" value={n(d.automatic)} />
      </div>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        <Chip tone={d.scheduler.enabled ? 'amber' : 'grey'}>Planificateur {d.scheduler.enabled ? 'activé' : 'désactivé'}</Chip>
        <Chip tone={d.remote_lock.remote_launch_enabled ? 'red' : 'green'}>Verrou distant {d.remote_lock.remote_launch_enabled ? 'ouvert' : 'fermé'}</Chip>
        {d.uncertain_proposals > 0 && <Chip tone="red">{d.uncertain_proposals} réponse(s) incertaine(s)</Chip>}
      </div>
    </div>
  )}</BlockState>;
}

function Datasets({ res, goto }: { res: Resource<Block<DatasetsData>>; goto: (p: Record<string, string>) => void }) {
  return <BlockState res={res} label="Les datasets">{(d) => <>
    {d.expected.length > 0 && <div className="ov-expected"><b>Attendus, non publiés :</b> {d.expected.map((e) => e.dataset_id).join(', ')}</div>}
    {d.items.length === 0 ? <Unavailable tone="grey">Aucune famille de datasets.</Unavailable> : (
      <div className="tf-table-wrap"><table className="tf-table ov-table"><thead><tr><th>Famille</th><th>Cas d’usage</th><th className="num">Versions</th><th>Dernière</th><th className="num">Images</th></tr></thead>
        <tbody>{d.items.map((f) => (
          <tr key={f.dataset_id} tabIndex={0} onClick={() => goto({ section: 'datasets', dataset: f.dataset_id })}>
            <td><b>{f.name}</b><small>{f.dataset_id}{f.synthetic ? ' · synthétique' : ''}</small></td><td>{uc(f.use_case)}</td>
            <td className="num">{f.versions}</td><td>{f.latest_version ?? '—'}</td><td className="num">{n(f.latest_images)}</td>
          </tr>))}</tbody></table></div>)}
  </>}</BlockState>;
}
