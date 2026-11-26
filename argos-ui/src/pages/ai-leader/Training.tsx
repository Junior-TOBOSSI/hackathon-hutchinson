import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { mlops, type JobRunInfo } from '../../api/mlops';
import { Badge, grid, KV, LinkButton, Loading, Panel, Technical, Unavailable, useNav } from './common';
import { errText, useExperiments, useJobRuns, useJobs, useRuns, useStore, useTrainingDataset } from './data';
import { dateTime, duration } from './metrics';
import { MetricsBlock } from './Registry';
import { useSelection } from './selection';

const POLL_MS = 10000;
const POLL_MAX = 60; // 10 minutes au plus

const stateTone = (r: JobRunInfo | null) =>
  !r ? 'grey' : r.result_state === 'SUCCESS' ? 'green' : r.result_state ? 'red' : 'blue';
const stateLabel = (r: JobRunInfo | null) =>
  !r ? 'jamais exécuté' : r.result_state === 'SUCCESS' ? 'réussi' : r.result_state ? r.result_state.toLowerCase() : (r.life_cycle_state ?? '').toLowerCase();

export default function Training({ onMessage }: { onMessage: (m: string) => void }) {
  const { go } = useNav();
  const store = useStore();
  const { model, status, loading, error } = useSelection();
  const jobs = useJobs();
  const experiments = useExperiments();
  const experiment = experiments.data?.[0] ?? null;
  const runs = useRuns(experiment?.experiment_id ?? null);
  const job = jobs.data?.find((j) => j.name === model?.training_job) ?? null;
  const history = useJobRuns(job?.job_id ?? null);
  const [active, setActive] = useState<JobRunInfo | null>(null);
  const [params] = useSearchParams();
  const selectedDataset = params.get('dataset');
  const jobDataset = useTrainingDataset(model?.id ?? null);
  const configured = jobDataset.data?.dataset_version ?? null;

  useEffect(() => {
    if (!active || active.life_cycle_state === 'TERMINATED' || active.life_cycle_state === 'INTERNAL_ERROR') return;
    let polls = 0;
    const timer = setInterval(() => {
      polls += 1;
      mlops.jobRun(active.run_id).then((r) => {
        setActive(r);
        if (r.life_cycle_state === 'TERMINATED' || polls >= POLL_MAX) { clearInterval(timer); store.invalidate('jobs', 'jobruns', 'runs:', 'statuses', 'overview'); }
      }).catch(() => clearInterval(timer));
    }, POLL_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.run_id]);

  if (error) return <Unavailable tone="red">{error}</Unavailable>;
  if (loading || !model) return <Loading />;
  const versionByRun = new Map((status?.versions ?? []).map((v) => [v.version.run_id, v.version.version]));

  const trigger = () => {
    if (!model.training_job) return;
    const data = configured ? `\nDataset utilisé : ${configured} (configuration actuelle du job).` : '';
    if (!window.confirm(`Relancer l'entraînement de « ${model.display_name} » ?\n\nExécute le job Databricks existant « ${model.training_job} » (calcul serverless facturé, une seule exécution à la fois). Aucun déploiement n'en découle.${data}`)) return;
    mlops.retrain(model.id)
      .then((r) => { setActive(r); onMessage(`Job ${model.training_job} démarré (exécution ${r.run_id}).`); })
      .catch((e) => onMessage(`Entraînement refusé : ${errText(e)}`));
  };

  return (
    <>
      <Panel title="Dataset d'entraînement" sub="Lu dans la définition du job Databricks (paramètre --dataset-dir)">
        {jobDataset.loading && <Loading />}
        {jobDataset.error && <Unavailable tone="red">Configuration du job indisponible : {jobDataset.error}</Unavailable>}
        {jobDataset.data && (
          <span style={{ fontSize: 15 }}>
            {configured ? <>Le job utilise actuellement <b>{configured}</b>.</> : <span className="muted">Dataset du job non déterminé ({jobDataset.data.source}).</span>}{' '}
            <LinkButton onClick={() => go('datasets', model.id)}>Voir les datasets</LinkButton>
          </span>
        )}
        {selectedDataset && configured && selectedDataset !== configured && (
          <Unavailable>
            Dataset sélectionné : <b>{selectedDataset}</b>. Le job actuel utilise encore <b>{configured}</b> : un entraînement lancé maintenant porterait sur {configured}, pas sur {selectedDataset}.
            Le choix du dataset d'entraînement sera raccordé avec DBX-05.
          </Unavailable>
        )}
        {selectedDataset && selectedDataset === configured && <span className="muted" style={{ fontSize: 14 }}>Le dataset sélectionné ({selectedDataset}) est celui du job.</span>}
      </Panel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: 18, alignItems: 'start' }}>
        <Panel title="Job d'entraînement" sub={model.training_job ? `Lakeflow Job « ${model.training_job} » · serverless CPU · déclenchement manuel` : undefined}>
          {!model.training_job && <Unavailable tone="grey">Aucun job d'entraînement déclaré pour ce modèle.</Unavailable>}
          {jobs.error && <Unavailable tone="red">{jobs.error}</Unavailable>}
          {model.training_job && jobs.data && !job && <Unavailable tone="red">Le job déclaré n'existe pas dans Databricks.</Unavailable>}
          {job && (
            <>
              <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
                <Badge tone={stateTone(job.last_run)}>{stateLabel(job.last_run)}</Badge>
                <span className="muted" style={{ fontSize: 14 }}>{job.last_run ? `dernière exécution ${dateTime(job.last_run.start_time)} · ${job.last_run.duration_s ?? '—'} s` : ''}</span>
                {!job.scheduled && <Badge tone="grey">aucune planification</Badge>}
              </div>
              {active && (
                <Unavailable tone="grey">Exécution {active.run_id} : {stateLabel(active)} {active.duration_s != null ? `· ${active.duration_s} s` : '· suivi toutes les 10 s'}</Unavailable>
              )}
              <div><button className="btn btn-primary" onClick={trigger} disabled={!job.triggerable || (!!active && active.life_cycle_state !== 'TERMINATED')}>Relancer l'entraînement</button></div>
              <span className="muted" style={{ fontSize: 13 }}>Le backend refuse un second déclenchement si une exécution est déjà active.</span>
              <b style={{ fontSize: 15 }}>Historique des exécutions</b>
              {history.loading && <Loading />}
              {history.error && <Unavailable tone="red">{history.error}</Unavailable>}
              <div className="col" style={{ gap: 6 }}>
                {history.data?.map((r) => (
                  <div key={r.run_id} className="between" style={{ fontSize: 14, padding: '6px 10px', borderRadius: 10, background: 'var(--surface-soft)', flexWrap: 'wrap' }}>
                    <span>{dateTime(r.start_time)}</span>
                    <span className="muted">{r.duration_s != null ? `${r.duration_s} s` : '—'}</span>
                    <Badge tone={stateTone(r)}>{stateLabel(r)}</Badge>
                  </div>
                ))}
              </div>
              <Technical title="Identifiants Databricks"><KV k="job_id" v={job.job_id} />{history.data?.slice(0, 3).map((r) => <KV key={r.run_id} k="run" v={r.run_id} />)}</Technical>
            </>
          )}
        </Panel>

        <Panel title="Configuration d'entraînement">
          <Unavailable tone="grey">
            La configuration est définie par le code du job (paramètres visibles dans chaque run MLflow ci-dessous).
            L'édition d'une configuration depuis HOVIS n'est pas encore raccordée (DBX-05).
          </Unavailable>
          <span className="muted" style={{ fontSize: 14 }}>Expérience MLflow : {experiment ? experiment.name : experiments.error ? 'indisponible' : '…'}</span>
        </Panel>
      </div>

      <Panel title="Runs MLflow" sub="Chaque run = un entraînement réel, avec ses mesures hors ligne">
        {runs.error && <Unavailable tone="red">{runs.error}</Unavailable>}
        {runs.loading && <Loading />}
        <div style={grid(340)}>
          {runs.data?.map((r) => {
            const version = versionByRun.get(r.run_id);
            return (
              <div key={r.run_id} className="col" style={{ gap: 10, padding: 16, borderRadius: 16, background: 'var(--surface-soft)' }}>
                <div className="between" style={{ flexWrap: 'wrap' }}>
                  <b style={{ fontSize: 17 }}>{r.run_name}</b>
                  <div className="row" style={{ gap: 6 }}>
                    <Badge tone={r.status === 'FINISHED' ? 'green' : 'red'}>{r.status === 'FINISHED' ? 'terminé' : r.status}</Badge>
                    {r.tags['argos.selection_role'] && <Badge tone="blue">{r.tags['argos.selection_role']}</Badge>}
                  </div>
                </div>
                <span className="muted" style={{ fontSize: 14 }}>{dateTime(r.start_time)} · durée {duration(r.start_time, r.end_time)}{version ? ' · ' : ''}{version && <LinkButton onClick={() => go('registry', model.id)}>version v{version}</LinkButton>}</span>
                <MetricsBlock run={r} compact />
                <Technical>
                  <KV k="run_id" v={r.run_id} />
                  {Object.entries(r.params).map(([k, v]) => <KV key={k} k={`param ${k}`} v={v} />)}
                  {Object.entries(r.tags).filter(([k]) => !k.startsWith('mlflow.')).map(([k, v]) => <KV key={k} k={`tag ${k}`} v={v} />)}
                </Technical>
              </div>
            );
          })}
        </div>
      </Panel>
    </>
  );
}
