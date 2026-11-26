import { useEffect, useState, type ReactNode } from 'react';
import {
  ApiError, mlops, type Comparison, type EndpointInfo, type JobRunInfo, type LiveOverview,
  type ModelStatus, type MonitoringReport, type RunSummary,
} from '../api/mlops';
import { Icon, ICONS, TopBar } from '../components/ui';
import { useApi } from '../hooks/useApi';

/* Espace AI Leader branché sur les VRAIES données Databricks (via le backend ARGOS).
   Règles : aucune donnée inventée ; un état indisponible est affiché comme tel ;
   approbation, alias champion et version servie sont trois informations distinctes. */

const GROUP_SLOTS = [
  { name: 'Quality Inspection', group: 'Groupe Quality', useCase: 'Qualité' },
  { name: 'PPE Detection', group: 'Groupe PPE', useCase: 'EPI' },
  { name: 'Behavior Detection', group: 'Groupe Behavior', useCase: 'Comportement' },
];
const METRICS = ['val_accuracy', 'val_precision_nok', 'val_recall_nok', 'val_f1_nok', 'test_accuracy', 'test_recall_nok', 'test_f1_nok'];
const JOB_POLL_MS = 10000;
const JOB_POLL_MAX = 60; // 10 minutes au plus

const pct = (v: number | null | undefined) => (v == null ? 'indisponible' : `${Math.round(v * 100)} %`);
const date = (iso: string | null) => (iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '—');
const errText = (e: unknown) => (e instanceof ApiError ? `${e.status || 'réseau'} · ${e.message}` : String(e));

function Card({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <div className="card col" style={{ gap: 12, overflowX: 'auto' }}>
      <div className="between"><h2 className="h2">{title}</h2>{right}</div>
      {children}
    </div>
  );
}

function State({ error, loading }: { error?: string | null; loading?: boolean }) {
  if (error) return <div className="pill pill-red" style={{ whiteSpace: 'normal', padding: '10px 14px' }}>Indisponible : {error}</div>;
  if (loading) return <div className="muted">Chargement…</div>;
  return null;
}

const th = { padding: '6px 10px 6px 0', textAlign: 'left' as const, fontSize: 13, letterSpacing: '0.04em' };
const td = { padding: '8px 10px 8px 0', borderTop: '1px solid var(--line-soft)', verticalAlign: 'top' as const };

/* ------------------------------------------------------------------ registre */

function Registry({ modelId, onChanged }: { modelId: string; onChanged: (msg: string) => void }) {
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [runs, setRuns] = useState<Record<string, RunSummary>>({});
  const [error, setError] = useState<string | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setError(null);
    mlops.status(modelId)
      .then(async (s) => {
        setStatus(s);
        const ids = s.versions.map((v) => v.version.run_id).filter((x): x is string => !!x);
        const loaded = await Promise.all(ids.map((id) => mlops.run(id)));
        setRuns(Object.fromEntries(loaded.map((r) => [r.run_id, r])));
      })
      .catch((e) => setError(errText(e)));
  };
  useEffect(load, [modelId]);

  const act = async (label: string, confirmText: string, action: () => Promise<unknown>) => {
    if (!window.confirm(confirmText)) return;
    setBusy(true);
    try {
      await action();
      onChanged(`${label} : confirmé par le backend.`);
      load();
    } catch (e) {
      onChanged(`${label} : échec (${errText(e)}).`);
    } finally {
      setBusy(false);
    }
  };

  if (!status) return <State error={error} loading />;
  const served = Object.entries(status.served);
  const runIds = status.versions.map((v) => v.version.run_id).filter((x): x is string => !!x);

  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="row" style={{ gap: 10, flexWrap: 'wrap', fontSize: 14 }}>
        <span className="pill pill-green">Approuvée = décision humaine (tag)</span>
        <span className="pill pill-blue">Champion = alias Unity Catalog</span>
        <span className="pill pill-amber">Servie = ce que l'endpoint exécute réellement</span>
      </div>
      <div className="muted" style={{ fontSize: 14 }}>
        {status.uc_name} · champion → v{status.aliases.champion ?? '—'} ·{' '}
        {served.length ? served.map(([e, v]) => `${e} sert v${v ?? '—'}`).join(' · ') : 'aucun endpoint'}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 980, fontSize: 14 }}>
        <thead className="muted"><tr>
          <th style={th}>VERSION</th><th style={th}>ALIAS</th><th style={th}>APPROBATION</th><th style={th}>SERVIE</th>
          <th style={th}>DATASET</th><th style={th}>ENTRAÎNÉE LE</th><th style={th}>MÉTRIQUES (MLflow)</th><th style={th}>RUN MLFLOW</th><th style={th} />
        </tr></thead>
        <tbody>
          {status.versions.map((vs) => {
            const v = vs.version;
            const run = v.run_id ? runs[v.run_id] : undefined;
            const isChampion = vs.aliases.includes('champion');
            return (
              <tr key={v.version}>
                <td style={{ ...td, fontWeight: 700 }}>v{v.version}</td>
                <td style={td}>{vs.aliases.length ? vs.aliases.map((a) => <span key={a} className="pill pill-blue" style={{ marginRight: 4 }}>{a}</span>) : '—'}</td>
                <td style={td}>{vs.approved ? <span className="pill pill-green">approuvée</span> : <span className="muted">non approuvée</span>}</td>
                <td style={td}>{vs.served_by.length ? <span className="pill pill-amber">servie ({vs.served_by.join(', ')})</span> : <span className="muted">non servie</span>}</td>
                <td style={td}>{run?.params.dataset_version ?? v.tags.argos_dataset_version ?? '—'}</td>
                <td style={td}>{date(run?.start_time ?? v.created_at)}</td>
                <td style={td}>
                  {run ? METRICS.filter((k) => k in run.metrics).map((k) => <div key={k}>{k} <b>{run.metrics[k].toFixed(3)}</b></div>) : <span className="muted">chargement…</span>}
                </td>
                <td style={td} title={v.run_id ?? ''}><code>{v.run_id ? `${v.run_id.slice(0, 8)}…` : '—'}</code></td>
                <td style={{ ...td, whiteSpace: 'nowrap' }}>
                  <div className="col" style={{ gap: 6 }}>
                    {!vs.approved && (
                      <button className="btn btn-ghost" disabled={busy} onClick={() => act(`Approbation v${v.version}`,
                        `Approuver la version ${v.version} ?\n\nCela ajoute seulement le tag d'approbation dans Unity Catalog. Aucun alias n'est déplacé, rien n'est déployé.`,
                        () => mlops.approve(modelId, v.version))}>Approuver</button>
                    )}
                    {!isChampion && (
                      <button className="btn btn-dark" disabled={busy} onClick={() => act(`Alias champion → v${v.version}`,
                        `Déplacer l'alias « champion » vers la version ${v.version} ?\n\nC'est une promotion dans le registre uniquement : la version servie par l'endpoint NE CHANGE PAS. Aucun déploiement n'est déclenché.`,
                        () => mlops.promote(modelId, v.version))}>Définir champion</button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {runIds.length >= 2 && (
        <div className="col" style={{ gap: 8 }}>
          <div className="row"><button className="btn btn-soft" onClick={() => mlops.compare(runIds).then(setComparison).catch((e) => setError(errText(e)))}>Comparer les versions (métriques MLflow)</button><State error={error} /></div>
          {comparison && (
            <table style={{ borderCollapse: 'collapse', fontSize: 14 }}>
              <thead className="muted"><tr><th style={th}>MÉTRIQUE</th>{status.versions.map((vs) => <th key={vs.version.version} style={th}>v{vs.version.version}</th>)}</tr></thead>
              <tbody>
                {METRICS.filter((m) => comparison.metrics[m]).map((m) => (
                  <tr key={m}><td style={td}>{m}</td>{status.versions.map((vs) => {
                    const value = vs.version.run_id ? comparison.metrics[m][vs.version.run_id] : null;
                    return <td key={vs.version.version} style={{ ...td, fontWeight: 600 }}>{value == null ? '—' : value.toFixed(3)}</td>;
                  })}</tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ entraînement */

function Training({ trainable, onMessage }: { trainable: { id: string; name: string; job: string }[]; onMessage: (m: string) => void }) {
  const experiments = useApi(() => mlops.experiments(), []);
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const jobs = useApi(() => mlops.jobs(), []);
  const [active, setActive] = useState<JobRunInfo | null>(null);

  useEffect(() => {
    const first = experiments.data?.[0];
    if (first) mlops.runs(first.experiment_id).then(setRuns).catch(() => setRuns([]));
  }, [experiments.data]);

  useEffect(() => {
    if (!active || active.life_cycle_state === 'TERMINATED' || active.life_cycle_state === 'INTERNAL_ERROR') return;
    let polls = 0;
    const timer = setInterval(() => {
      polls += 1;
      mlops.jobRun(active.run_id).then((r) => {
        setActive(r);
        if (r.life_cycle_state === 'TERMINATED' || polls >= JOB_POLL_MAX) { clearInterval(timer); jobs.reload(); }
      }).catch(() => clearInterval(timer));
    }, JOB_POLL_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.run_id]);

  const retrain = (id: string, name: string, job: string) => {
    if (!window.confirm(`Relancer l'entraînement de « ${name} » ?\n\nCela exécute le job Databricks existant « ${job} » (calcul serverless facturé, une seule exécution à la fois). Aucun déploiement n'en découle.`)) return;
    mlops.retrain(id)
      .then((r) => { setActive(r); onMessage(`Job ${job} démarré (run ${r.run_id}).`); })
      .catch((e) => onMessage(`Réentraînement refusé : ${errText(e)}`));
  };

  return (
    <Card title="Entraînements · MLflow et Lakeflow Jobs">
      <State error={experiments.error ?? jobs.error} loading={!experiments.data || !jobs.data} />
      {experiments.data && (
        <div className="muted" style={{ fontSize: 14 }}>Expériences : {experiments.data.map((e) => `${e.name} (id ${e.experiment_id})`).join(' · ') || 'aucune'}</div>
      )}
      {runs && (
        <table style={{ borderCollapse: 'collapse', fontSize: 14, minWidth: 640 }}>
          <thead className="muted"><tr><th style={th}>RUN</th><th style={th}>ÉTAT</th><th style={th}>DÉBUT</th><th style={th}>VAL F1 NOK</th><th style={th}>TEST F1 NOK</th><th style={th}>RÔLE</th></tr></thead>
          <tbody>{runs.map((r) => (
            <tr key={r.run_id}><td style={td}>{r.run_name}</td><td style={td}>{r.status}</td><td style={td}>{date(r.start_time)}</td>
              <td style={td}>{r.metrics.val_f1_nok?.toFixed(3) ?? '—'}</td><td style={td}>{r.metrics.test_f1_nok?.toFixed(3) ?? '—'}</td>
              <td style={td}>{r.tags['argos.selection_role'] ?? '—'}</td></tr>
          ))}</tbody>
        </table>
      )}
      {jobs.data && (
        <table style={{ borderCollapse: 'collapse', fontSize: 14, minWidth: 640 }}>
          <thead className="muted"><tr><th style={th}>JOB</th><th style={th}>DERNIÈRE EXÉCUTION</th><th style={th}>DURÉE</th><th style={th}>PLANIFIÉ</th></tr></thead>
          <tbody>{jobs.data.map((j) => (
            <tr key={j.job_id}><td style={td}>{j.name}</td>
              <td style={td}>{j.last_run ? `${j.last_run.life_cycle_state} ${j.last_run.result_state ?? ''} · ${date(j.last_run.start_time)}` : '—'}</td>
              <td style={td}>{j.last_run?.duration_s != null ? `${j.last_run.duration_s} s` : '—'}</td>
              <td style={td}>{j.scheduled ? 'oui' : 'non (manuel)'}</td></tr>
          ))}</tbody>
        </table>
      )}
      {active && <div className="pill pill-blue" style={{ padding: '10px 14px' }}>Run {active.run_id} : {active.life_cycle_state} {active.result_state ?? ''} {active.duration_s != null ? `· ${active.duration_s} s` : ''}</div>}
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {trainable.map((t) => <button key={t.id} className="btn btn-primary" onClick={() => retrain(t.id, t.name, t.job)}>Relancer l'entraînement · {t.name}</button>)}
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ serving et monitoring */

function Serving({ endpoints, error }: { endpoints: EndpointInfo[] | null; error: string | null }) {
  return (
    <Card title="Model Serving" right={<span className="muted" style={{ fontSize: 13 }}>changement de version servie : non disponible (chantier suivant)</span>}>
      <State error={error} loading={!endpoints} />
      {endpoints?.length === 0 && <div className="muted">Aucun endpoint personnalisé.</div>}
      {endpoints?.map((e) => (
        <div key={e.name} className="row" style={{ gap: 18, flexWrap: 'wrap' }}>
          <b>{e.name}</b>
          <span className={`pill ${e.ready === 'READY' ? 'pill-green' : 'pill-red'}`}>{e.ready ?? 'inconnu'}</span>
          <span className="muted">mise à jour : {e.config_update ?? '—'}</span>
          {e.served.map((s) => <span key={s.name ?? ''}>sert <b>{s.model} v{s.version}</b> · {s.workload_size} · scale to zero {s.scale_to_zero ? 'activé' : 'désactivé'} · {s.deployment}</span>)}
        </div>
      ))}
    </Card>
  );
}

function DriftTable({ report, title }: { report: MonitoringReport; title: string }) {
  if (!report.metrics) return null;
  return (
    <div className="col" style={{ gap: 8 }}>
      <b>{title}</b>
      <div className="muted" style={{ fontSize: 14 }}>Table {report.table} · modèle {report.metrics.model.registered_model} v{report.metrics.model.version} · calculé le {date(report.metrics.window_end)} · {report.metrics.n_inferences} inférences</div>
      <table style={{ borderCollapse: 'collapse', fontSize: 14 }}>
        <thead className="muted"><tr><th style={th}>VARIABLE</th><th style={th}>MÉTHODE</th><th style={th}>VALEUR</th><th style={th}>SEUIL</th><th style={th}>ÉTAT</th></tr></thead>
        <tbody>{report.metrics.drift.map((d) => (
          <tr key={d.feature}><td style={td}>{d.feature}</td><td style={td}>{d.method.toUpperCase()}</td><td style={{ ...td, fontWeight: 700 }}>{d.value.toFixed(2)}</td><td style={td}>{d.threshold}</td>
            <td style={td}>{d.alert ? <span className="pill pill-red">dérive</span> : <span className="pill pill-green">stable</span>}</td></tr>
        ))}</tbody>
      </table>
      <div style={{ fontSize: 14 }}>Exactitude étiquetée : référence {pct(report.accuracies.accuracy_reference)} · scénario dérivé {pct(report.accuracies.accuracy_drift)}</div>
    </div>
  );
}

function Monitoring({ modelId }: { modelId: string }) {
  const [report, setReport] = useState<MonitoringReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = (refresh: boolean) => { setError(null); mlops.monitoring(modelId, refresh).then(setReport).catch((e) => setError(errText(e))); };
  useEffect(() => load(false), [modelId]);
  return (
    <Card title="Monitoring · dérive des données" right={<button className="btn btn-ghost" onClick={() => load(true)}>Actualiser</button>}>
      <State error={error} loading={!report && !error} />
      {report && !report.available && (
        <div className="pill pill-amber" style={{ whiteSpace: 'normal', padding: '10px 14px' }}>
          Lecture en direct indisponible : {report.reason}. Le serveur ne démarre jamais le SQL warehouse automatiquement (économie de crédits).
        </div>
      )}
      {report?.available && report.metrics && <DriftTable report={report} title="Lecture en direct" />}
      {report && !report.available && report.last_snapshot?.metrics && (
        <DriftTable report={report.last_snapshot} title={`Dernier résultat connu (lu le ${date(report.last_snapshot.read_at)}) — pas une lecture en direct`} />
      )}
      {report && !report.available && !report.last_snapshot && <div className="muted">Aucun résultat antérieur enregistré.</div>}
      <div className="muted" style={{ fontSize: 13 }}>Une dérive des données (luminosité, flou, distribution des scores) n'est pas une preuve de dérive de concept.</div>
    </Card>
  );
}

/* ------------------------------------------------------------------ page */

export default function AiLeaderLive() {
  const health = useApi(() => mlops.health(), [], 60000);
  const overview = useApi(() => mlops.overview(), []);
  const endpoints = useApi(() => mlops.endpoints(), []);
  const managed = useApi(() => mlops.models(), []);
  const trainable = (managed.data ?? [])
    .filter((m) => m.training_job)
    .map((m) => ({ id: m.id, name: m.display_name, job: m.training_job as string }));
  const [msg, setMsg] = useState('');
  const ov: LiveOverview | null = overview.data;
  const models = ov?.models ?? [];

  const setMode = (mode: 'MANUEL' | 'AUTO') =>
    mlops.setRetrainMode(mode).then(() => { overview.reload(); setMsg(`Préférence « ${mode} » enregistrée (en mémoire du serveur).`); })
      .catch((e) => setMsg(`Échec : ${errText(e)}`));

  const connection = health.error
    ? <span className="pill pill-solid-red">Databricks : {health.error}</span>
    : health.data ? <span className="pill pill-green">Databricks connecté · profil {health.data.profile}</span> : <span className="pill pill-blue">Connexion…</span>;

  return (
    <div className="screen">
      <TopBar title="Fabrique de modèles" sub="AI Leader · données réelles Databricks" right={connection} />
      <main className="col" style={{ padding: '20px 24px', gap: 18 }}>
        <div className="row stack-mobile" style={{ flexWrap: 'wrap' }}>
          <span className="grow" style={{ fontWeight: 600 }}>{msg}</span>
          <span className="muted" style={{ fontWeight: 600 }}>Réentraînement</span>
          <div className="row" style={{ background: '#fff', border: '2px solid var(--line)', borderRadius: 26, padding: 4, gap: 0 }}>
            {(['MANUEL', 'AUTO'] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)} className="btn" style={{ borderRadius: 22, background: ov?.retrainMode === m ? 'var(--navy)' : 'transparent', color: ov?.retrainMode === m ? '#fff' : 'var(--muted)' }}>{m === 'AUTO' ? 'Auto (préférence)' : 'Manuel'}</button>
            ))}
          </div>
          <button className="btn btn-ghost" onClick={() => { health.reload(); overview.reload(); endpoints.reload(); }}><span className="row" style={{ gap: 6 }}><Icon d={ICONS.overview} size={18} />Actualiser</span></button>
        </div>
        <div className="muted" style={{ fontSize: 13 }}>Le mode AUTO est une préférence enregistrée en mémoire : aucun réentraînement automatique n'est encore implémenté.</div>

        <Card title="Modèles" right={<span className="muted" style={{ fontSize: 13 }}>{ov?.dataStatus.healthPct ? `Santé : ${ov.dataStatus.healthPct}` : ''}</span>}>
          <State error={overview.error} loading={!ov} />
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 900, fontSize: 15 }}>
            <thead className="muted"><tr><th style={th}>MODÈLE</th><th style={th}>CAS</th><th style={th}>VERSION SERVIE</th><th style={th}>CHAMPION</th><th style={th}>APPROUVÉE(S)</th><th style={th}>SANTÉ</th><th style={th}>RAPPEL NOK</th></tr></thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.id}>
                  <td style={{ ...td, fontWeight: 600 }}>{m.name} {m.synthetic && <span className="pill pill-amber">DÉMO SYNTHÉTIQUE</span>}</td>
                  <td style={td}>{m.useCase}</td><td style={td}>{m.servedVersion ? `v${m.servedVersion}` : 'non servi'}</td>
                  <td style={td}>{m.championVersion ? `v${m.championVersion}` : '—'}</td>
                  <td style={td}>{m.approvedVersions.length ? m.approvedVersions.map((v) => `v${v}`).join(', ') : 'aucune'}</td>
                  <td style={td}>{m.healthPct == null ? 'indisponible' : `${m.healthPct} %`}</td>
                  <td style={td}>{m.recallKoPct == null ? 'indisponible' : `${m.recallKoPct} %`}</td>
                </tr>
              ))}
              {GROUP_SLOTS.map((s) => (
                <tr key={s.name} className="muted">
                  <td style={{ ...td, fontWeight: 600 }}>{s.name}</td><td style={td}>{s.useCase}</td>
                  <td style={td} colSpan={5}><span className="pill pill-blue">En attente de livraison · {s.group}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <div className="row stack-mobile" style={{ gap: 18, alignItems: 'stretch' }}>
          <div className="grow col" style={{ gap: 18 }}>
            <Card title="Dérives signalées">
              {ov && ov.drifts.length === 0 && <div className="muted">Aucune dérive signalée (ou monitoring indisponible, voir ci-dessous).</div>}
              {ov?.drifts.map((d) => <div key={d.modelId} className="col" style={{ gap: 4, padding: '12px 14px', borderRadius: 16, border: `2px solid ${d.stale ? 'var(--amber)' : 'var(--red)'}` }}><b>{d.title}</b><span className="muted" style={{ fontSize: 14 }}>{d.detail}</span></div>)}
            </Card>
          </div>
          <div className="card col" style={{ width: 440, maxWidth: '100%' }}>
            <h2 className="h2">Santé sur 14 jours</h2>
            <div className="muted">Historique indisponible : aucun job de monitoring quotidien n'existe encore. Aucune courbe n'est simulée.</div>
          </div>
        </div>

        {models.map((m) => (
          <Card key={m.id} title={`Registre · ${m.name}`} right={m.synthetic ? <span className="pill pill-amber">DÉMO SYNTHÉTIQUE</span> : undefined}>
            <Registry modelId={m.id} onChanged={(text) => { setMsg(text); overview.reload(); endpoints.reload(); }} />
          </Card>
        ))}

        <Serving endpoints={endpoints.data} error={endpoints.error} />
        {models[0] && <Monitoring modelId={models[0].id} />}
        <Training trainable={trainable} onMessage={setMsg} />
      </main>
    </div>
  );
}
