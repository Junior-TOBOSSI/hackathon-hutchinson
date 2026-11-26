import type { ReactNode } from 'react';
import type { EndpointInfo, JobInfo, LiveOverview, ModelStatus } from '../../api/mlops';
import { Badge, grid, LinkButton, Loading, Panel, Stat, Unavailable, useNav, type Section } from './common';
import { useEndpoints, useExperiments, useHealth, useJobs, useOverview, useRuns, useStatuses } from './data';
import { dateTime, duration } from './metrics';
import { PENDING_SLOTS, useSelection, versionRoles } from './selection';

interface Alert { level: 'red' | 'amber' | 'blue'; title: string; detail: string; section: Section; model?: string }

/** Alertes calculées UNIQUEMENT depuis les réponses réelles de l'API. */
function computeAlerts(overview: LiveOverview | null, statuses: ModelStatus[] | null, endpoints: EndpointInfo[] | null, jobs: JobInfo[] | null): Alert[] {
  const alerts: Alert[] = [];
  for (const d of overview?.drifts ?? []) {
    alerts.push({ level: d.stale ? 'amber' : 'red', title: `Dérive des données · ${d.title}`, detail: d.detail, section: 'monitoring', model: d.modelId });
  }
  for (const s of statuses ?? []) {
    const { served, champion, championApproved } = versionRoles(s);
    if (champion && served && champion !== served) {
      alerts.push({ level: 'amber', title: `Champion v${champion} non servi`, detail: `L'endpoint sert encore v${served}. Le déploiement d'une version n'est pas encore disponible dans ARGOS.`, section: 'deployment', model: s.model_id });
    }
    if (champion && championApproved === false) {
      alerts.push({ level: 'amber', title: `Champion v${champion} non approuvé`, detail: "L'alias champion désigne une version sans approbation humaine.", section: 'registry', model: s.model_id });
    }
  }
  for (const e of endpoints ?? []) {
    if (e.ready !== 'READY') alerts.push({ level: 'red', title: `Endpoint ${e.name} indisponible`, detail: `État : ${e.ready ?? 'inconnu'} · mise à jour : ${e.config_update ?? '—'}`, section: 'deployment' });
  }
  for (const j of jobs ?? []) {
    if (j.last_run?.result_state && j.last_run.result_state !== 'SUCCESS') {
      alerts.push({ level: 'red', title: `Dernière exécution en échec · ${j.name}`, detail: `${j.last_run.result_state} · ${dateTime(j.last_run.start_time)}`, section: 'training' });
    }
  }
  for (const u of overview?.dataStatus.unavailable ?? []) {
    if (u.startsWith('monitoring')) alerts.push({ level: 'blue', title: 'Monitoring en direct indisponible', detail: u.replace(/^monitoring [^:]+: /, ''), section: 'monitoring' });
  }
  return alerts;
}

export default function Overview() {
  const { go } = useNav();
  const health = useHealth();
  const overview = useOverview();
  const statuses = useStatuses();
  const endpoints = useEndpoints();
  const jobs = useJobs();
  const experiments = useExperiments();
  const runs = useRuns(experiments.data?.[0]?.experiment_id ?? null);
  const { models, loading: modelsLoading, error: modelsError } = useSelection();

  // Last training = last run of the managed models' training jobs (already in /jobs).
  const trainingJobs = new Set(models.map((m) => m.training_job).filter(Boolean));
  const lastJob = (jobs.data ?? [])
    .filter((j) => trainingJobs.has(j.name) && j.last_run?.start_time)
    .sort((a, b) => (b.last_run?.start_time ?? '').localeCompare(a.last_run?.start_time ?? ''))[0];
  const versions = statuses.data?.reduce((n, s) => n + s.versions.length, 0);
  const readyEndpoints = endpoints.data?.filter((e) => e.ready === 'READY').length;
  const drifting = new Set((overview.data?.drifts ?? []).map((d) => d.modelId)).size;
  const alerts = computeAlerts(overview.data, statuses.data, endpoints.data, jobs.data);
  const v = (x: number | undefined, loading: boolean, error: string | null): ReactNode => (error ? '—' : x == null || loading ? '…' : x);

  return (
    <>
      <div style={grid(190)}>
        <Stat label="Connexion Databricks" value={health.error ? 'Coupée' : health.data ? 'Active' : '…'} tone={health.error ? 'red' : health.data ? 'green' : undefined} hint={health.error ?? (health.data ? `profil ${health.data.profile}` : undefined)} />
        <Stat label="Modèles enregistrés" value={v(models.length, modelsLoading, modelsError)} hint={`${PENDING_SLOTS.length} en attente de livraison`} onClick={() => go('registry')} />
        <Stat label="Versions disponibles" value={v(versions, statuses.loading, statuses.error)} hint="Unity Catalog" onClick={() => go('registry')} />
        <Stat label="Endpoints prêts" value={endpoints.error ? '—' : endpoints.data ? `${readyEndpoints} / ${endpoints.data.length}` : '…'} hint="Model Serving" onClick={() => go('deployment')} />
        <Stat label="Modèles en dérive" value={v(drifting, overview.loading, overview.error)} tone={drifting ? 'red' : 'green'} hint={overview.data?.drifts.some((d) => d.stale) ? "d'après le dernier instantané" : undefined} onClick={() => go('monitoring')} />
        <Stat label="Dernier job d'entraînement" value={lastJob?.last_run ? dateTime(lastJob.last_run.start_time).split(' ')[0] : jobs.error ? '—' : jobs.data ? 'aucun' : '…'} hint={lastJob?.last_run ? `${dateTime(lastJob.last_run.start_time).split(' ')[1]} · ${lastJob.last_run.result_state ?? lastJob.last_run.life_cycle_state ?? ''}` : undefined} onClick={() => go('training')} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 18 }}>
        <Panel title="Interventions" sub="Calculées depuis l'état réel du registre, du serving, des jobs et du monitoring">
          {overview.loading && <span className="muted" style={{ fontSize: 14 }}>Analyse du monitoring en cours… Les autres contrôles s'affichent dès qu'ils sont disponibles.</span>}
          {overview.error && <Unavailable tone="red">Synthèse indisponible : {overview.error}</Unavailable>}
          {!overview.loading && !statuses.loading && alerts.length === 0 && <Unavailable tone="grey">Aucune intervention nécessaire.</Unavailable>}
          {alerts.map((a, i) => (
            <button key={i} onClick={() => go(a.section, a.model)} className="col" style={{ textAlign: 'left', gap: 4, padding: '12px 14px', borderRadius: 14, cursor: 'pointer', background: '#fff', border: `2px solid ${a.level === 'red' ? 'var(--red)' : a.level === 'amber' ? 'var(--amber)' : 'var(--line-strong)'}` }}>
              <b>{a.title}</b>
              <span className="muted" style={{ fontSize: 14 }}>{a.detail}</span>
              <span style={{ fontSize: 13, color: 'var(--primary)', fontWeight: 700 }}>Ouvrir →</span>
            </button>
          ))}
        </Panel>

        <Panel title="Parc de modèles" sub="Modèles gérés par ARGOS et livraisons attendues">
          {statuses.error && <Unavailable tone="red">Registre indisponible : {statuses.error}</Unavailable>}
          {models.map((m) => {
            const s = statuses.data?.find((x) => x.model_id === m.id) ?? null;
            const { served, champion, approved } = versionRoles(s);
            const drift = overview.data?.drifts.find((d) => d.modelId === m.id);
            return (
              <div key={m.id} className="col" style={{ gap: 8, padding: '12px 14px', borderRadius: 14, background: 'var(--surface-soft)' }}>
                <div className="between" style={{ flexWrap: 'wrap' }}><b>{m.display_name}</b>{m.synthetic && <Badge tone="amber">Démo synthétique</Badge>}</div>
                <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                  <Badge tone={served ? 'amber' : 'grey'}>{served ? `servie v${served}` : 'non servi'}</Badge>
                  <Badge tone="blue">{champion ? `champion v${champion}` : 'pas de champion'}</Badge>
                  <Badge tone={approved.length ? 'green' : 'grey'}>{approved.length ? `approuvée ${approved.map((x) => `v${x}`).join(', ')}` : 'aucune approbation'}</Badge>
                  {drift && <Badge tone={drift.stale ? 'amber' : 'red'}>dérive{drift.stale ? ' (instantané)' : ''}</Badge>}
                </div>
                <div className="row" style={{ gap: 14, fontSize: 14, flexWrap: 'wrap' }}>
                  <LinkButton onClick={() => go('registry', m.id)}>Versions</LinkButton>
                  <LinkButton onClick={() => go('training', m.id)}>Entraînements</LinkButton>
                  <LinkButton onClick={() => go('datasets', m.id)}>Données</LinkButton>
                  <LinkButton onClick={() => go('monitoring', m.id)}>Monitoring</LinkButton>
                </div>
              </div>
            );
          })}
          {PENDING_SLOTS.map((p) => (
            <div key={p.name} className="between" style={{ padding: '10px 14px', borderRadius: 14, border: '1px dashed var(--line-strong)', flexWrap: 'wrap' }}>
              <span><b>{p.name}</b> <span className="muted">· {p.useCase}</span></span>
              <Badge tone="grey">En attente de livraison · {p.group}</Badge>
            </div>
          ))}
        </Panel>
      </div>

      <Panel title="Derniers entraînements" sub={experiments.data?.[0] ? `Expérience MLflow ${experiments.data[0].name}` : undefined} right={<LinkButton onClick={() => go('training')}>Training Factory →</LinkButton>}>
        {(runs.error || experiments.error) && <Unavailable tone="red">{runs.error ?? experiments.error}</Unavailable>}
        {runs.loading && <Loading />}
        <div style={grid(260)}>
          {runs.data?.slice(0, 3).map((r) => (
            <div key={r.run_id} className="col" style={{ gap: 4, padding: '12px 14px', borderRadius: 14, background: 'var(--surface-soft)' }}>
              <b>{r.run_name}</b>
              <span className="muted" style={{ fontSize: 14 }}>{dateTime(r.start_time)} · {duration(r.start_time, r.end_time)}</span>
              <div className="row" style={{ gap: 6 }}><Badge tone={r.status === 'FINISHED' ? 'green' : 'red'}>{r.status === 'FINISHED' ? 'terminé' : r.status}</Badge>{r.tags['argos.selection_role'] && <Badge tone="blue">{r.tags['argos.selection_role']}</Badge>}</div>
            </div>
          ))}
        </div>
      </Panel>
      <Panel title="Historique de santé sur 14 jours">
        <Unavailable tone="grey">Indisponible : aucun job de monitoring quotidien n'existe encore. Aucune courbe n'est simulée.</Unavailable>
      </Panel>
    </>
  );
}
