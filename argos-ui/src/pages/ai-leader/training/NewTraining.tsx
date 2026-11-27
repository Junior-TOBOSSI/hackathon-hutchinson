import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from '../../../api/mlops';
import { training, type LaunchRecord, type ParamSpec, type PipelineSpec, type ValidationReport } from '../../../api/training';
import { Loading, Unavailable } from '../common';
import { errText, useDatasetFamily, useStore } from '../data';
import { SPLIT_FR } from '../DatasetExplorer';
import { Chip, classColor, Donut, fr, SelectField, SPLIT_BLUES, StackedBar } from '../ui';
import { useCompatible, usePipelines, usePreview, useTfParams } from './shared';

const STEPS = ['Configuration', 'Validation', 'Exécution'];

/* Assistant « Nouvel entraînement » : les paramètres viennent de la déclaration du
   pipeline ; les contrôles affichés sont ceux calculés par le backend. */
export default function NewTraining() {
  const nav = useTfParams();
  const store = useStore();
  const pipelines = usePipelines();
  const [step, setStep] = useState(0);
  const [pipelineId, setPipelineId] = useState(nav.pipeline ?? '');
  const [datasetId, setDatasetId] = useState(nav.dataset ?? '');
  const [version, setVersion] = useState(nav.dsversion ?? '');
  const [values, setValues] = useState<Record<string, unknown>>(() => { try { return nav.prefill ? JSON.parse(nav.prefill) : {}; } catch { return {}; } });
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');
  const compat = useCompatible(pipelineId || null);
  const family = useDatasetFamily(datasetId || null);
  const preview = usePreview(datasetId || null, version || null);
  const view = pipelines.data?.find((p) => p.spec.id === pipelineId) ?? null;
  const spec = view?.spec ?? null;

  useEffect(() => { // default pipeline: the one compatible with the dataset coming from Datasets
    if (!pipelineId && pipelines.data?.length) setPipelineId(pipelines.data.find((p) => !nav.dataset || p.spec.dataset.families.includes(nav.dataset))?.spec.id ?? pipelines.data[0].spec.id);
  }, [pipelines.data, pipelineId, nav.dataset]);
  useEffect(() => { // latest version by default
    const versions = family.data?.versions ?? [];
    if (datasetId && !version && versions.length) setVersion(versions[versions.length - 1].version);
  }, [family.data, datasetId, version]);

  const params = useMemo(() => {
    const out: Record<string, unknown> = {};
    for (const p of spec?.parameters ?? []) if (p.level !== 'imposed' && values[p.name] !== undefined && values[p.name] !== p.default) out[p.name] = values[p.name];
    return out;
  }, [spec, values]);
  const key = JSON.stringify([pipelineId, datasetId, version, params]);
  useEffect(() => { // real backend checks, debounced
    if (!pipelineId || !datasetId || !version) { setReport(null); return; }
    let cancelled = false;
    setChecking(true);
    const t = window.setTimeout(() => {
      training.validate({ pipeline_id: pipelineId, dataset_id: datasetId, version, parameters: params })
        .then((r) => { if (!cancelled) { setReport(r); setError(''); } })
        .catch((e) => { if (!cancelled) setError(errText(e)); })
        .finally(() => { if (!cancelled) setChecking(false); });
    }, 400);
    return () => { cancelled = true; window.clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const close = () => nav.set({}, true);
  return (
    <section className="card tf-panel">
      <div className="between" style={{ flexWrap: 'wrap', gap: 10 }}>
        <h2 className="h2" style={{ fontSize: 22 }}>Nouvel entraînement</h2>
        <button className="btn btn-ghost" aria-label="Fermer" onClick={close}>✕</button>
      </div>
      <div className="tf-steps">{STEPS.map((s, i) => <span key={s} style={{ display: 'contents' }}>
        {i > 0 && <hr />}<span className={`tf-step${i === step ? ' active' : i < step ? ' done' : ''}`}><b>{i + 1}</b>{s}</span></span>)}</div>
      {pipelines.loading && <Loading what="Lecture des pipelines" />}
      {pipelines.error && <Unavailable tone="red">{pipelines.error}</Unavailable>}
      {error && <Unavailable tone="red">Contrôles indisponibles : {error}</Unavailable>}

      {step === 0 && pipelines.data && <div className="tf-config">
        <div className="col" style={{ gap: 12, minWidth: 0 }}>
          <SelectField label="Pipeline / modèle" icon="none" value={pipelineId} onChange={(v) => { setPipelineId(v); setValues({}); }}
            options={pipelines.data.map((p) => [p.spec.id, `${p.spec.name}${p.executable ? '' : ' — non exécutable'}`])} />
          {view && !view.executable && <Unavailable>Pipeline non exécutable : {view.requirements.filter((r) => !r.ok).map((r) => `${r.label} (${r.detail ?? 'non satisfait'})`).join(' ; ')}</Unavailable>}
          <SelectField label="Dataset" icon="none" allLabel="Choisir un dataset compatible" value={datasetId} onChange={(v) => { setDatasetId(v); setVersion(''); }}
            options={(compat.data ?? []).map((d) => [d.family.dataset_id, `${d.family.name} (${d.family.dataset_id})${d.family.version_count ? '' : ' — aucune version'}`])} />
          {compat.data && compat.data.length === 0 && <Unavailable tone="grey">Aucun dataset publié compatible (classes {spec?.classes.join(', ')}).</Unavailable>}
          <SelectField label="Version du dataset" icon="none" allLabel="Choisir une version" value={version} onChange={setVersion}
            options={[...(family.data?.versions ?? [])].reverse().map((v) => [v.version, `${v.version} (${v.ref.num_samples} images)`])} />
          {spec && <Params specs={spec.parameters} values={values} onChange={setValues} />}
          {spec && <div className="tf-box"><b>Environnement de calcul</b>
            <span>{spec.compute.gpu ? 'GPU' : 'Databricks serverless CPU'} · job « {String(spec.job.name)} »</span>
            <span className="muted" style={{ fontSize: 13 }}>{(spec.compute.environment as string[] | undefined)?.join(', ')}</span></div>}
        </div>
        <div className="col" style={{ gap: 12, minWidth: 0 }}>
          <DatasetPreviewBox preview={preview} />
          <div className="tf-box"><b>Contrôles de compatibilité</b>{checking && <span className="muted">Vérification…</span>}
            {report ? <Checks checks={report.checks.filter((c) => !c.id.startsWith('param:'))} compact /> : <span className="muted">Choisir un pipeline, un dataset et une version.</span>}</div>
        </div>
      </div>}

      {step === 1 && report && <Validation report={report} spec={spec} />}
      {step === 2 && report && <Execute report={report} pipelineId={pipelineId} datasetId={datasetId} version={version} params={params}
        onDone={(r) => { store.invalidate('training:'); if (r.job_run_id) nav.set({ run: String(r.job_run_id) }, true); }} />}

      <div className="row" style={{ justifyContent: 'space-between', gap: 10 }}>
        <button className="btn btn-ghost" onClick={() => (step ? setStep(step - 1) : setValues({}))}>{step ? '← Retour' : 'Réinitialiser'}</button>
        {step < 2 && <button className="btn btn-primary" disabled={!report || checking || (step === 1 && !report.launchable)}
          onClick={() => setStep(step + 1)}>{step === 0 ? 'Suivant : Validation →' : 'Suivant : Exécution →'}</button>}
      </div>
    </section>
  );
}

function Params({ specs, values, onChange }: { specs: ParamSpec[]; values: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const [advanced, setAdvanced] = useState(false);
  if (!specs.length) return <div className="tf-box"><b>Paramètres d'entraînement</b><span className="muted">Ce pipeline n'expose aucun hyperparamètre : sa configuration est fixée par son code.</span></div>;
  const field = (p: ParamSpec) => (
    <label key={p.name} title={p.help ?? undefined}>{p.label}
      <input type="number" step={p.type === 'float' ? 0.01 : 1} min={p.min ?? undefined} max={p.max ?? undefined}
        value={String(values[p.name] ?? p.default)} onChange={(e) => onChange({ ...values, [p.name]: p.type === 'int' ? Number.parseInt(e.target.value, 10) : Number(e.target.value) })} />
    </label>);
  return <div className="tf-box"><b>Paramètres d'entraînement</b>
    <div className="tf-params">{specs.filter((p) => p.level === 'basic').map(field)}</div>
    <button className="btn" style={{ background: 'none', color: 'var(--primary)', padding: 0, height: 'auto', alignSelf: 'flex-start' }} onClick={() => setAdvanced(!advanced)}>
      {advanced ? '▾' : '▸'} Paramètres avancés</button>
    {advanced && <div className="tf-params">{specs.filter((p) => p.level === 'advanced').map(field)}</div>}
    <span className="muted" style={{ fontSize: 13 }}>Imposés par l'intégration : {specs.filter((p) => p.level === 'imposed').map((p) => `${p.label} = ${String(p.default)}`).join(' · ') || 'aucun'}</span>
  </div>;
}

function DatasetPreviewBox({ preview }: { preview: ReturnType<typeof usePreview> }) {
  const p = preview.data;
  return <div className="tf-box">
    <b>Aperçu du dataset{p ? ` (${p.version})` : ''}</b>
    {preview.loading && <Loading what="Lecture du manifeste" />}
    {preview.error && <Unavailable tone="red">{preview.error}</Unavailable>}
    {!p && !preview.loading && <span className="muted">Aucune version sélectionnée.</span>}
    {p && <>
      <span><b>{p.num_images.toLocaleString('fr-FR')} images</b> · {p.classes.length} classes{p.synthetic ? ' · synthétique' : ''}{p.groups ? ` · ${p.groups} rafales/groupes` : ''}</span>
      <Donut size={130} items={p.classes.map((c, i) => ({ label: c, count: p.class_counts[c] ?? 0, color: classColor(c, i) }))} />
      <StackedBar items={['train', 'validation', 'test'].map((s, i) => ({ label: SPLIT_FR[s] ?? s, count: p.split_counts[s] ?? 0, color: SPLIT_BLUES[i] }))} />
      {!p.split_counts.validation && <Unavailable>Aucun split de validation : les pipelines qui en ont besoin refusent ce dataset.</Unavailable>}
      <span className="muted" style={{ fontSize: 13 }}>Découpage : {fr(p.split_strategy)} · manifeste SHA-256 {p.manifest_sha256.slice(0, 12)}…</span>
    </>}
  </div>;
}

export function Checks({ checks, compact }: { checks: ValidationReport['checks']; compact?: boolean }) {
  const icon = { ok: ['✓', 'var(--green-text)'], warning: ['!', 'var(--amber-text)'], error: ['✕', 'var(--red-text)'] } as const;
  return <div className="col" style={{ gap: compact ? 6 : 8 }}>{checks.map((c) => (
    <div key={c.id} className="tf-check"><b style={{ color: icon[c.status][1] }}>{icon[c.status][0]}</b>
      <span>{c.label}{c.detail && <small>{c.detail}</small>}</span></div>))}</div>;
}

function Validation({ report, spec }: { report: ValidationReport; spec: PipelineSpec | null }) {
  const errors = report.checks.filter((c) => c.status === 'error');
  return <div className="col" style={{ gap: 12 }}>
    {errors.length > 0 ? <Unavailable tone="red">Lancement bloqué : {errors.map((e) => e.label).join(', ')}.</Unavailable>
      : <Unavailable tone="grey">Tous les contrôles indispensables sont satisfaits.</Unavailable>}
    <div className="tf-config">
      <div className="tf-box"><b>Récapitulatif</b>
        <span>Pipeline : <b>{spec?.name}</b></span>
        <span className="muted" style={{ fontSize: 13 }}>Code : {report.code.version ?? report.code.commit ?? '—'}</span>
        {report.dataset && <span>Dataset : <b>{report.dataset.dataset_id}</b> version <b>{report.dataset.version}</b> ({report.dataset.num_images} images)</span>}
        <span>Calcul : {report.compute.gpu ? 'GPU' : 'serverless CPU'} · résultats MLflow : {report.mlflow.experiment}</span>
        <span>Modèle candidat : {report.mlflow.registered_model} (jamais approuvé, promu ni déployé automatiquement)</span>
        <b>Hyperparamètres effectifs</b>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>{Object.keys(report.parameters).length
          ? Object.entries(report.parameters).map(([k, v]) => <Chip key={k} tone="grey">{k} = {String(v)}</Chip>) : <span className="muted">aucun (fixés par le code)</span>}</div>
        <b>Commandes</b><pre className="tf-pre">{report.command_preview.join('\n')}</pre>
      </div>
      <div className="tf-box"><b>Contrôles</b><Checks checks={report.checks} /></div>
    </div>
  </div>;
}

function Execute({ report, pipelineId, datasetId, version, params, onDone }: {
  report: ValidationReport; pipelineId: string; datasetId: string; version: string; params: Record<string, unknown>; onDone: (r: LaunchRecord) => void;
}) {
  const keyRef = useRef(crypto.randomUUID()); // ONE key for this confirmation: retries reuse it
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<LaunchRecord | null>(null);
  const [error, setError] = useState('');
  const launch = async () => {
    setBusy(true); setError('');
    try {
      const r = await training.launch({ pipeline_id: pipelineId, dataset_id: datasetId, version, parameters: params, idempotency_key: keyRef.current });
      setResult(r); onDone(r);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 403 ? 'Lancement distant non autorisé pour le moment : aucun job n\'a été déclenché.'
        : `${errText(e)} — résultat incertain : relancer réutilise la même clé, aucun second job ne sera créé.`);
    } finally { setBusy(false); }
  };
  return <div className="col" style={{ gap: 12 }}>
    <div className="tf-box"><b>Confirmation</b>
      <span>Le job Databricks du pipeline sera déclenché avec <b>{datasetId} {version}</b>. Calcul serverless CPU facturé ; une seule exécution par confirmation.</span>
      <label className="row" style={{ gap: 8, alignItems: 'center' }}><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> Je confirme le lancement de cet entraînement.</label>
      <button className="btn btn-primary" style={{ alignSelf: 'flex-start' }} disabled={!confirmed || busy || !report.launchable || !!result} onClick={launch}>{busy ? 'Envoi…' : 'Lancer l\'entraînement'}</button>
      <span className="muted" style={{ fontSize: 12 }}>Clé d'idempotence : {keyRef.current}</span>
    </div>
    {error && <Unavailable tone="red">{error}</Unavailable>}
    {result && <Unavailable tone="grey">Job déclenché : exécution {result.job_run_id} ({result.status}). Le suivi s'affiche dans le détail de l'entraînement.</Unavailable>}
  </div>;
}
