import { useEffect, useMemo, useState } from 'react';
import { Icon, ICONS } from '../../../components/ui';
import { Badge, Loading, Unavailable } from '../common';
import { useHealth, useStore } from '../data';
import { Chip, Kpi, SearchField, SelectField } from '../ui';
import NewTraining from './NewTraining';
import RunDetail from './RunDetail';
import { dt, duration, StatusChip, useTfParams, useTrainingRuns, useTrainingSummary } from './shared';
import './training.css';

const PAGE = 10;
const PERIODS: [string, string][] = [['7', '7 derniers jours'], ['30', '30 derniers jours'], ['90', '90 derniers jours'], ['all', 'Toute la période']];

/* Training Factory (DBX-05) : vue agrégée par défaut, catalogue des entraînements
   (Databricks Jobs + MLflow), panneau de droite « Nouvel entraînement » ou « Détail ». */
export default function TrainingFactory(_props: { onMessage?: (m: string) => void }) {
  const store = useStore();
  const health = useHealth();
  const runs = useTrainingRuns();
  const summary = useTrainingSummary();
  const nav = useTfParams();
  const [query, setQuery] = useState('');
  const [pipeline, setPipeline] = useState('');
  const [dataset, setDataset] = useState('');
  const [status, setStatus] = useState('');
  const [period, setPeriod] = useState('30');
  const [sort, setSort] = useState('date');
  const [page, setPage] = useState(0);
  const rows = runs.data ?? [];
  const active = rows.some((r) => r.status === 'running' || r.status === 'queued');

  // Polling ONLY while a training is active (DBX-PERF-01).
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => store.invalidate('training:runs', 'training:summary'), 15_000);
    return () => window.clearInterval(timer);
  }, [active, store]);

  const filtered = useMemo(() => {
    const since = period === 'all' ? '' : new Date(Date.now() - Number(period) * 86400_000).toISOString();
    const qy = query.toLocaleLowerCase();
    return rows
      .filter((r) => (!pipeline || r.pipeline_id === pipeline) && (!dataset || r.dataset_id === dataset) && (!status || r.status === status))
      .filter((r) => !since || (r.started_at ?? '') >= since)
      .filter((r) => `${r.id} ${r.pipeline_id} ${r.dataset_id ?? ''} ${r.dataset_version ?? ''} ${r.mlflow_runs.join(' ')}`.toLocaleLowerCase().includes(qy))
      .sort((a, b) => sort === 'duration' ? (b.duration_s ?? 0) - (a.duration_s ?? 0)
        : sort === 'old' ? (a.started_at ?? '').localeCompare(b.started_at ?? '') : (b.started_at ?? '').localeCompare(a.started_at ?? ''));
  }, [rows, pipeline, dataset, status, period, query, sort]);
  const visible = filtered.slice(page * PAGE, page * PAGE + PAGE);
  const panel = nav.isNew || nav.run != null;
  const k = summary.data;
  const fresh = runs.cache === 'stale' ? ['Dernier résultat connu', 'amber'] : runs.refreshing ? ['Actualisation…', 'blue']
    : runs.cache === 'hit' ? ['Cache serveur', 'blue'] : runs.data ? ['Données à jour', 'green'] : ['Chargement…', 'grey'];
  const uniq = (values: (string | null)[]) => Array.from(new Set(values.filter((v): v is string => !!v))).sort();

  return (
    <div className="tf">
      <header className="card tf-hero">
        <div className="tf-hero-title">
          <span className="tf-hero-icon"><Icon d={ICONS.play} size={24} /></span>
          <div><h1 className="h2">Training Factory — Entraînements</h1>
            <p className="muted">Configurer, lancer et suivre les entraînements de modèles sur Databricks.</p></div>
        </div>
        <div className="row" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <span className="muted" style={{ fontSize: 13 }}>Dernière synchronisation : {runs.fetchedAt ? dt(runs.fetchedAt) : '—'}</span>
          <Chip tone={fresh[1] as 'green'}>{fresh[0]}</Chip>
          <Badge tone={health.error ? 'red' : health.data?.ok ? 'green' : 'amber'}>{health.error ? 'Databricks indisponible' : health.data?.ok ? 'Databricks connecté' : 'Connexion…'}</Badge>
          <button className="btn btn-ghost" disabled={runs.refreshing} onClick={() => store.invalidate('training:')}>Actualiser</button>
        </div>
      </header>
      {runs.staleError && <Unavailable>Dernière actualisation en échec : {runs.staleError}</Unavailable>}

      <div className="tf-kpis">
        <Kpi icon="layers" label="Entraînements (30 jours)" value={k ? k.trainings_30d : summary.error ? '—' : '…'} />
        <Kpi icon="check" label="Terminés" value={k ? k.succeeded : '…'} tone={k?.succeeded ? 'green' : undefined} hint={k && k.trainings_30d ? `${Math.round((k.succeeded * 100) / k.trainings_30d)} %` : undefined} />
        <Kpi icon="play" label="En cours" value={k ? k.running : '…'} />
        <Kpi icon="warn" label="En échec" value={k ? k.failed : '…'} tone={k?.failed ? 'red' : undefined} />
        <Kpi icon="db" label="Pipelines disponibles" value={k ? `${k.pipelines_executable} / ${k.pipelines_total}` : '…'} hint="exécutables / déclarés" />
        <Kpi icon="badge" label="Candidats en attente" value={k ? k.candidates : '…'} hint={k ? `sans approbation ni alias · ${k.versions_produced} versions produites` : undefined} />
        <Kpi icon="log" label="Dernier entraînement" value={k?.last_training_at ? dt(k.last_training_at) : k ? 'aucun' : '…'} hint={k?.last_training_label ?? undefined} />
      </div>
      {summary.error && !k && <Unavailable tone="red">Indicateurs indisponibles : {summary.error}</Unavailable>}

      <div className={`tf-layout${panel ? '' : ' full'}`}>
        <section className="card tf-panel tf-catalog">
          <div className="between" style={{ gap: 10, flexWrap: 'wrap' }}>
            <h2 className="h2" style={{ fontSize: 21 }}>Entraînements récents</h2>
            <button className="btn btn-primary" onClick={() => nav.set({ new: '1' }, true)}>＋ Nouvel entraînement</button>
          </div>
          <div className="tf-filters">
            <SearchField placeholder="Rechercher (identifiant, pipeline, dataset, run…)" value={query} onChange={(v) => { setQuery(v); setPage(0); }} />
            <SelectField label="Statut" allLabel="Tous les statuts" value={status} onChange={(v) => { setStatus(v); setPage(0); }}
              options={[['succeeded', 'Terminé'], ['running', 'En cours'], ['queued', 'En attente'], ['failed', 'Échec'], ['cancelled', 'Annulé']]} />
            <SelectField label="Pipeline" allLabel="Tous les pipelines" value={pipeline} onChange={(v) => { setPipeline(v); setPage(0); }} options={uniq(rows.map((r) => r.pipeline_id)).map((p) => [p, p])} />
            <SelectField label="Dataset" allLabel="Tous les datasets" value={dataset} onChange={(v) => { setDataset(v); setPage(0); }} options={uniq(rows.map((r) => r.dataset_id)).map((d) => [d, d])} />
            <SelectField label="Période" icon="none" value={period} onChange={(v) => { setPeriod(v); setPage(0); }} options={PERIODS} />
            <SelectField label="Tri" icon="sort" value={sort} onChange={setSort} options={[['date', 'Plus récents'], ['old', 'Plus anciens'], ['duration', 'Durée']]} />
          </div>
          {runs.loading && <Loading what="Lecture des jobs Databricks et des runs MLflow" />}
          {runs.error && !runs.data && <Unavailable tone="red">Catalogue indisponible : {runs.error}</Unavailable>}
          {runs.data && <span className="muted" style={{ fontSize: 13 }}>{filtered.length} résultat(s)</span>}
          {runs.data && filtered.length === 0 && <Unavailable tone="grey">Aucun entraînement pour ces critères.</Unavailable>}
          {visible.length > 0 && <div className="tf-table-wrap"><table className="tf-table"><thead><tr>
            <th>Entraînement</th><th>Pipeline</th><th>Dataset (version)</th><th>Statut</th><th className="opt">Durée</th><th className="opt">Début</th><th className="opt">Modèle produit</th><th className="opt">Actions</th>
          </tr></thead><tbody>{visible.map((r) => (
            <tr key={r.id} className={nav.run === r.job_run_id ? 'selected' : ''} tabIndex={0} onClick={() => nav.set({ run: String(r.job_run_id) }, true)}
              onKeyDown={(e) => { if (e.key === 'Enter') nav.set({ run: String(r.job_run_id) }, true); }}>
              <td><b>{r.id}</b><small>{r.mlflow_runs.length ? `run ${r.mlflow_runs[0].slice(0, 8)}…${r.mlflow_runs.length > 1 ? ` +${r.mlflow_runs.length - 1}` : ''}` : 'aucun run MLflow relié'}</small></td>
              <td>{r.pipeline_id}<small>{r.pipeline_name}</small></td>
              <td>{r.dataset_id ?? '—'}<small>{r.dataset_version ?? 'version inconnue'}</small></td>
              <td><StatusChip status={r.status} /></td>
              <td className="opt">{duration(r.duration_s)}</td>
              <td className="opt">{dt(r.started_at)}</td>
              <td className="opt">{r.model_versions.length ? r.model_versions.map((v) => <Chip key={v} tone="blue">v{v}</Chip>) : '—'}</td>
              <td className="opt"><button className="btn btn-ghost" style={{ height: 34 }} onClick={(e) => { e.stopPropagation(); nav.set({ run: String(r.job_run_id) }, true); }}>Ouvrir</button></td>
            </tr>))}</tbody></table></div>}
          {filtered.length > PAGE && <div className="row" style={{ justifyContent: 'flex-end', gap: 8, alignItems: 'center' }}>
            <button className="btn btn-ghost" disabled={!page} onClick={() => setPage(page - 1)}>Précédent</button>
            <span className="muted">{page + 1} / {Math.ceil(filtered.length / PAGE)}</span>
            <button className="btn btn-ghost" disabled={(page + 1) * PAGE >= filtered.length} onClick={() => setPage(page + 1)}>Suivant</button>
          </div>}
        </section>
        {nav.isNew && <NewTraining key={`${nav.pipeline}:${nav.dataset}:${nav.dsversion}`} />}
        {!nav.isNew && nav.run != null && <RunDetail key={nav.run} jobRunId={nav.run} />}
      </div>
    </div>
  );
}
