import { useEffect, useState } from 'react';
import { familyImageUrl, type RunSummary } from '../../../api/mlops';
import { artifactUrl, training, type MlRun, type Point, type PredictionPage, type RunDetail as Detail } from '../../../api/training';
import { KV, Loading, Technical, Unavailable } from '../common';
import { errText, useStore } from '../data';
import { MetricsBlock } from '../Registry';
import { Chip, SelectField } from '../ui';
import { duration, dt, num, pct, StatusChip, useArtifacts, useEvaluation, useHistory, useLogs, useRunDetail, useTfParams } from './shared';

const TABS = ['Vue d’ensemble', 'Métriques', 'Évaluation', 'Prédictions', 'Configuration', 'Artefacts', 'Logs'] as const;
type Tab = (typeof TABS)[number];

export default function RunDetail({ jobRunId }: { jobRunId: number }) {
  const nav = useTfParams();
  const store = useStore();
  const detail = useRunDetail(jobRunId);
  const [runIndex, setRunIndex] = useState(0);
  const [predFilter, setPredFilter] = useState<Record<string, string>>({});
  const [message, setMessage] = useState('');
  const tab = (TABS.find((t) => t === nav.tab) ?? TABS[0]) as Tab;
  const d = detail.data;
  const run = d?.runs[runIndex] ?? null;
  const go = (t: Tab) => nav.set({ tab: t });

  const cancel = async () => {
    if (!window.confirm(`Annuler l'exécution ${jobRunId} ?`)) return;
    try { await training.cancel(jobRunId); store.invalidate('training:'); setMessage('Annulation demandée.'); }
    catch (e) { setMessage(errText(e)); }
  };
  const webapp = run?.tags['mlflow.databricks.webappURL'];
  return (
    <section className="card tf-panel">
      {detail.loading && <Loading what="Lecture de l'entraînement" />}
      {detail.error && <Unavailable tone="red">{detail.error}</Unavailable>}
      {d && <>
        <div className="between" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <div className="col" style={{ gap: 4 }}>
            <div className="row" style={{ gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><h2 className="h2" style={{ fontSize: 22 }}>{d.row.id} — {d.row.pipeline_id}</h2><StatusChip status={d.row.status} /></div>
            <span className="muted" style={{ fontSize: 13 }}>Pipeline : {d.pipeline.name} · Dataset : {d.row.dataset_id ?? '—'} ({d.row.dataset_version ?? 'version inconnue'}) · Durée : {duration(d.row.duration_s)} · Début : {dt(d.row.started_at)}</span>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            {d.row.run_page_url && <a className="btn btn-ghost" href={d.row.run_page_url} target="_blank" rel="noreferrer">Ouvrir dans Databricks ↗</a>}
            {webapp && run && <a className="btn btn-ghost" href={`${webapp}/ml/experiments/${(run as unknown as RunSummary & { experiment_id?: string }).experiment_id ?? ''}/runs/${run.run_id}`} target="_blank" rel="noreferrer">Ouvrir dans MLflow ↗</a>}
            {d.row.model_versions.length > 0 && <button className="btn btn-ghost" onClick={() => nav.set({ section: 'registry', run: null, tab: null })}>Modèle candidat v{d.row.model_versions.join(', v')}</button>}
            {(d.row.status === 'running' || d.row.status === 'queued') && <button className="btn btn-ghost" onClick={cancel}>Annuler</button>}
            <button className="btn btn-ghost" aria-label="Fermer" onClick={() => nav.set({}, true)}>✕</button>
          </div>
        </div>
        {message && <Unavailable>{message}</Unavailable>}
        {d.runs.length > 1 && <div style={{ maxWidth: 420 }}><SelectField label="Run MLflow" icon="none" value={String(runIndex)} onChange={(v) => setRunIndex(Number(v))}
          options={d.runs.map((r, i) => [String(i), `${r.run_name ?? r.run_id} (${r.tags['argos.selection_role'] ?? 'run'})`])} /></div>}
        {!run && <Unavailable tone="grey">Aucun run MLflow relié à cette exécution (tag databricks.job_run_id absent) : résultats indisponibles.</Unavailable>}
        <nav className="tf-tabs">{TABS.map((t) => <button key={t} className={t === tab ? 'active' : ''} onClick={() => go(t)}>{t}</button>)}</nav>
        {run && tab === 'Vue d’ensemble' && <Overview d={d} run={run} />}
        {run && tab === 'Métriques' && <Metrics run={run} />}
        {run && tab === 'Évaluation' && <Evaluation run={run} onCell={(t, p) => { setPredFilter({ true: t, pred: p }); go('Prédictions'); }} />}
        {run && tab === 'Prédictions' && <Predictions run={run} d={d} filter={predFilter} setFilter={setPredFilter} />}
        {run && tab === 'Configuration' && <Configuration d={d} run={run} />}
        {run && tab === 'Artefacts' && <Artifacts run={run} />}
        {tab === 'Logs' && <Logs id={jobRunId} />}
      </>}
    </section>
  );
}

function metric(run: MlRun, ...keys: string[]) {
  for (const k of keys) if (run.metrics[k] != null) return run.metrics[k];
  return null;
}

function Overview({ d, run }: { d: Detail; run: MlRun }) {
  const cards: [string, string, string?][] = [
    ['Exactitude (test)', pct(metric(run, 'test_accuracy'))],
    ['Rappel NOK (test)', pct(metric(run, 'test_rappel', 'test_recall_nok'))],
    ['Faux rejets (test)', pct(metric(run, 'test_faux_rejets'))],
    ['NOK déclarés OK (test)', pct(metric(run, 'test_nok_declarees_ok'))],
    ['F1 NOK (test)', pct(metric(run, 'test_f1_nok'))],
    ['Latence moyenne', metric(run, 'test_latence_ms_moyenne') != null ? `${metric(run, 'test_latence_ms_moyenne')} ms` : '—'],
    ['Latence P95', metric(run, 'test_latence_ms_p95') != null ? `${metric(run, 'test_latence_ms_p95')} ms` : '—'],
    ['Durée d’entraînement', duration(metric(run, 'train_duration_s', 'train_time_s') ?? d.row.duration_s)],
    ['Époques (réalisées / meilleure)', metric(run, 'epochs_done') != null ? `${metric(run, 'epochs_done')} / ${metric(run, 'best_epoch')}` : '—'],
    ['Modèle produit', d.row.model_versions.length ? `v${d.row.model_versions.join(', v')} (candidat)` : '—'],
  ];
  return <div className="col" style={{ gap: 12 }}>
    <div className="tf-metric-grid">{cards.map(([label, value]) => <div key={label} className="tf-box"><span className="muted" style={{ fontSize: 13 }}>{label}</span><b style={{ fontSize: 22 }}>{value}</b></div>)}</div>
    <span className="muted" style={{ fontSize: 13 }}>Mesures par image sur le split test indépendant ; « — » = non mesuré par ce pipeline. Aucune conversion en mesure par pièce.
      {metric(run, 'early_stopped') ? ' Arrêt anticipé (patience atteinte).' : ''}</span>
    {metric(run, 'test_rappel', 'test_accuracy') == null && <Unavailable tone="grey">Aucune métrique de test pour ce run.</Unavailable>}
  </div>;
}

function Metrics({ run }: { run: MlRun }) {
  const hist = useHistory(run.run_id);
  const series = Object.entries(hist.data ?? {}).filter(([, pts]) => pts.length > 1);
  if (hist.loading) return <Loading what="Lecture de l'historique MLflow" />;
  if (hist.error) return <Unavailable tone="red">{hist.error}</Unavailable>;
  if (!series.length) return <Unavailable tone="grey">Ce pipeline n'enregistre pas de métriques par époque : aucune courbe à afficher (aucune courbe simulée).</Unavailable>;
  const best = metric(run, 'best_epoch');
  return <div className="col" style={{ gap: 14 }}>
    <LineChart title="Pertes" series={series.filter(([k]) => k.includes('loss'))} best={best} />
    <LineChart title="Exactitude" series={series.filter(([k]) => k.includes('accuracy'))} best={best} ratio />
    <span className="muted" style={{ fontSize: 13 }}>Exactitude mesurée sur la validation (Ultralytics ne fournit pas d'exactitude d'entraînement).{best != null ? ` Meilleure époque : ${best}.` : ''}</span>
  </div>;
}

const COLORS = ['var(--primary)', 'var(--red)', 'var(--navy)', '#e08a1e', '#0f9d9a'];
const LABELS: Record<string, string> = { train_loss: 'Perte (train)', val_loss: 'Perte (validation)', val_accuracy_top1: 'Exactitude top-1 (validation)', val_accuracy_top5: 'Exactitude top-5 (validation)' };

function LineChart({ title, series, best, ratio }: { title: string; series: [string, Point[]][]; best: number | null; ratio?: boolean }) {
  const [hidden, setHidden] = useState<string[]>([]);
  const [hover, setHover] = useState<number | null>(null);
  if (!series.length) return null;
  const shown = series.filter(([k]) => !hidden.includes(k));
  const all = shown.flatMap(([, p]) => p);
  const xs = series.flatMap(([, p]) => p.map((x) => x.step));
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const ymax = ratio ? 1 : Math.max(0.0001, ...all.map((p) => p.value));
  const W = 640, H = 220, L = 40, B = 24;
  const sx = (x: number) => L + ((x - x0) / Math.max(1, x1 - x0)) * (W - L - 10);
  const sy = (y: number) => 8 + (1 - y / ymax) * (H - B - 8);
  return <div className="tf-box"><b>{title}</b>
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }} onMouseLeave={() => setHover(null)}
      onMouseMove={(e) => { const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect(); const x = x0 + ((e.clientX - r.left) / r.width * W - L) / (W - L - 10) * (x1 - x0); setHover(Math.round(Math.min(x1, Math.max(x0, x)))); }}>
      {[0, 0.25, 0.5, 0.75, 1].map((t) => <g key={t}><line x1={L} x2={W - 10} y1={sy(t * ymax)} y2={sy(t * ymax)} stroke="var(--line)" /><text x={L - 6} y={sy(t * ymax) + 4} fontSize="10" textAnchor="end" fill="var(--muted)">{ratio ? `${Math.round(t * 100)}%` : (t * ymax).toFixed(2)}</text></g>)}
      {best != null && <line x1={sx(best)} x2={sx(best)} y1={8} y2={H - B} stroke="var(--green)" strokeDasharray="4 3" />}
      {shown.map(([k, pts]) => <polyline key={k} fill="none" strokeWidth="2" stroke={COLORS[series.findIndex(([s]) => s === k) % COLORS.length]}
        points={[...pts].sort((a, b) => a.step - b.step).map((p) => `${sx(p.step)},${sy(p.value)}`).join(' ')} />)}
      {hover != null && <line x1={sx(hover)} x2={sx(hover)} y1={8} y2={H - B} stroke="var(--muted)" strokeWidth="0.5" />}
      {xs.length > 0 && [x0, x1].map((x) => <text key={x} x={sx(x)} y={H - 6} fontSize="10" textAnchor="middle" fill="var(--muted)">époque {x}</text>)}
    </svg>
    {hover != null && <span style={{ fontSize: 13 }}>Époque {hover} : {shown.map(([k, p]) => `${LABELS[k] ?? k} ${p.find((x) => x.step === hover)?.value.toFixed(3) ?? '—'}`).join(' · ')}</span>}
    <div className="row" style={{ gap: 12, flexWrap: 'wrap', fontSize: 13 }}>{series.map(([k], i) => <label key={k} className="row" style={{ gap: 6, alignItems: 'center' }}>
      <input type="checkbox" checked={!hidden.includes(k)} onChange={() => setHidden(hidden.includes(k) ? hidden.filter((h) => h !== k) : [...hidden, k])} />
      <span className="hv-dot" style={{ background: COLORS[i % COLORS.length] }} />{LABELS[k] ?? k}</label>)}
      {best != null && <span className="muted">— pointillé vert : meilleure époque</span>}</div>
  </div>;
}

function Evaluation({ run, onCell }: { run: MlRun; onCell: (truth: string, pred: string) => void }) {
  const ev = useEvaluation(run.run_id);
  const [normalized, setNormalized] = useState(false);
  if (ev.loading) return <Loading what="Lecture des sorties d'évaluation" />;
  if (ev.error) return <Unavailable tone="red">{ev.error}</Unavailable>;
  const e = ev.data;
  if (!e?.available) return <div className="col" style={{ gap: 10 }}>
    <Unavailable tone="grey">Pas de fichiers d'évaluation (predictions.csv, metriques.json) pour ce run : matrice de confusion indisponible. Mesures enregistrées dans MLflow :</Unavailable>
    <MetricsBlock run={run as unknown as RunSummary} /></div>;
  const m = e.metrics as Record<string, unknown>;
  const cols = e.columns ?? [];
  return <div className="col" style={{ gap: 14 }}>
    <div className="tf-metric-grid">
      {([['Rappel NOK', pct(num(m.rappel))], ['Défauts déclarés OK', pct(num(m.nok_declarees_ok))], ['Faux rejets', pct(num(m.faux_rejets))],
        ['OK mis en doute', pct(num(m.a_verifier_ok))], ['Seuil NOK', String(m.seuil_nok ?? '—')], ['Photos évaluées', String(e.n ?? '—')]] as [string, string][]).map(([l, v]) =>
        <div key={l} className="tf-box"><span className="muted" style={{ fontSize: 13 }}>{l}</span><b style={{ fontSize: 20 }}>{v}</b></div>)}
    </div>
    {(e.n ?? 0) < 100 && <Unavailable>Petit effectif ({e.n} photos) : ces chiffres sont des ordres de grandeur.</Unavailable>}
    <div className="tf-box"><div className="between"><b>Matrice de confusion (split {e.split}) — lignes : vraie classe, colonnes : décision</b>
      <label className="row" style={{ gap: 6, fontSize: 13 }}><input type="checkbox" checked={normalized} onChange={(x) => setNormalized(x.target.checked)} />normalisée</label></div>
      <div style={{ overflowX: 'auto' }}><table className="tf-matrix"><thead><tr><th /> {cols.map((c) => <th key={c}>{c}</th>)}<th>Support</th></tr></thead>
        <tbody>{(e.truth_classes ?? []).map((t) => { const row = e.matrix?.[t] ?? {}; const total = Object.values(row).reduce((a, b) => a + b, 0);
          return <tr key={t}><th style={{ textAlign: 'right' }}>{t}</th>{cols.map((c) => { const n = row[c] ?? 0; const share = total ? n / total : 0;
            return <td key={c}><button title="Voir les prédictions" onClick={() => onCell(t, c)} style={{ background: c === t ? `rgba(47,111,214,${0.15 + share * 0.85})` : n ? `rgba(220,53,69,${0.12 + share * 0.6})` : 'var(--surface-soft)', color: share > 0.6 ? '#fff' : 'var(--ink)' }}>
              {normalized ? (total ? share.toFixed(3).replace('.', ',') : '—') : n}</button></td>; })}<td>{total}</td></tr>; })}</tbody></table></div>
      <span className="muted" style={{ fontSize: 13 }}>La colonne A_VERIFIER est conservée (seuil de doute du groupe). Cliquer une cellule ouvre les prédictions correspondantes.</span></div>
    <div className="tf-box"><b>Résultats par classe (décision du modèle)</b>
      <table className="tf-table"><thead><tr><th>Classe</th><th>Support</th><th>Précision</th><th>Rappel</th><th>F1</th></tr></thead>
        <tbody>{Object.entries(e.per_class ?? {}).map(([c, v]) => <tr key={c}><td>{c}</td><td>{v.support}</td><td>{pct(v.precision)}</td><td>{pct(v.recall)}</td><td>{pct(v.f1)}</td></tr>)}</tbody></table></div>
  </div>;
}

const KINDS: [string, string][] = [['correct', 'Correctes'], ['incorrect', 'Incorrectes'], ['false_reject', 'Faux rejets'], ['missed_defect', 'Défauts manqués'],
  ['type_confusion', 'Erreur de type de défaut'], ['to_check', 'À vérifier']];

function Predictions({ run, d, filter, setFilter }: { run: MlRun; d: Detail; filter: Record<string, string>; setFilter: (f: Record<string, string>) => void }) {
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<PredictionPage | null>(null);
  const [error, setError] = useState('');
  const datasetId = run.tags['argos.dataset_id'] ?? d.row.dataset_id ?? undefined;
  const version = run.tags['argos.dataset_version'] ?? d.row.dataset_version ?? undefined;
  const key = JSON.stringify([run.run_id, filter, offset]);
  useEffect(() => {
    setError('');
    training.predictions(run.run_id, { ...filter, dataset_id: datasetId, version, offset, limit: 24 }).then(setPage).catch((e) => setError(errText(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const classes = d.pipeline.classes;
  return <div className="col" style={{ gap: 12 }}>
    <div className="tf-filters">
      <SelectField label="Classe réelle" allLabel="Classe réelle : toutes" value={filter.true ?? ''} onChange={(v) => { setFilter({ ...filter, true: v }); setOffset(0); }} options={classes.map((c) => [c, c])} />
      <SelectField label="Décision" allLabel="Décision : toutes" value={filter.pred ?? ''} onChange={(v) => { setFilter({ ...filter, pred: v }); setOffset(0); }} options={[...classes, 'A_VERIFIER'].map((c) => [c, c])} />
      <SelectField label="Type" allLabel="Toutes les prédictions" value={filter.kind ?? ''} onChange={(v) => { setFilter({ ...filter, kind: v }); setOffset(0); }} options={KINDS} />
    </div>
    {error && <Unavailable tone="red">{error}</Unavailable>}
    {!page && !error && <Loading what="Lecture de predictions.csv" />}
    {page && !page.available && <Unavailable tone="grey">Ce run ne fournit pas de prédictions par image (predictions.csv absent).</Unavailable>}
    {page?.available && <>
      <span className="muted" style={{ fontSize: 13 }}>{page.total} prédiction(s) · split test · bordure verte = décision juste, rouge = erreur ; la pastille donne le verdict industriel.</span>
      <div className="tf-gallery">{page.items.map((p) => (
        <div key={`${p.vraie_classe}/${p.fichier}`} className={`tf-pred ${p.correct ? 'ok' : 'ko'}`}>
          {p.manifest_file && datasetId && version ? <img loading="lazy" decoding="async" alt={p.fichier} src={familyImageUrl(datasetId, version, p.manifest_file)} />
            : <div className="ph">image non reliée au manifeste</div>}
          <div className="row" style={{ gap: 4, flexWrap: 'wrap' }}><Chip tone={p.verdict === 'OK' ? 'green' : p.verdict === 'NOK' ? 'red' : 'amber'}>{p.verdict}</Chip>{p.type_defaut && <Chip tone="grey">{p.type_defaut}</Chip>}</div>
          <span>Réel : <b>{p.vraie_classe}</b> · décision : <b>{p.decision}</b></span>
          <span className="muted">Score NOK {p.score_nok?.toFixed(3) ?? '—'} · {p.latence_ms ?? '—'} ms</span>
          <span className="muted" title={p.fichier} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.fichier}</span>
        </div>))}</div>
      {page.total > 24 && <div className="row" style={{ gap: 8, justifyContent: 'flex-end', alignItems: 'center' }}>
        <button className="btn btn-ghost" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 24))}>Précédent</button>
        <span className="muted">{offset + 1}–{Math.min(offset + 24, page.total)} / {page.total}</span>
        <button className="btn btn-ghost" disabled={offset + 24 >= page.total} onClick={() => setOffset(offset + 24)}>Suivant</button></div>}
    </>}
  </div>;
}

function Configuration({ d, run }: { d: Detail; run: MlRun }) {
  const nav = useTfParams();
  const tags = Object.entries(run.tags).filter(([k]) => k.startsWith('hovis.') || k.startsWith('argos.') || k.startsWith('versions.') || k === 'python');
  const prepare = () => nav.set({ new: '1', pipeline: d.pipeline.id, dataset: d.row.dataset_id, dsversion: d.row.dataset_version, params: JSON.stringify(
    Object.fromEntries(d.pipeline.parameters.filter((p) => p.level !== 'imposed' && run.params[p.name] != null).map((p) => [p.name, p.type === 'str' ? run.params[p.name] : Number(run.params[p.name])]))) }, true);
  return <div className="col" style={{ gap: 12 }}>
    <div className="tf-config">
      <div className="tf-box"><b>Modèle et code</b><KV k="Architecture" v={d.pipeline.architecture} /><KV k="Code" v={d.pipeline.code.version ?? d.pipeline.code.commit ?? '—'} />
        <KV k="Dataset" v={`${d.row.dataset_id ?? '—'} ${d.row.dataset_version ?? ''}`} /><KV k="Manifeste SHA-256" v={run.tags['argos.manifest_sha256'] ?? '—'} />
        <KV k="Description" v={d.pipeline.description} /></div>
      <div className="tf-box"><b>Hyperparamètres effectifs</b>{Object.entries(run.params).map(([k, v]) => <KV key={k} k={k} v={v} />)}</div>
    </div>
    <Technical title="Traçabilité (tags du run)">{tags.map(([k, v]) => <KV key={k} k={k} v={v} />)}</Technical>
    <button className="btn btn-ghost" style={{ alignSelf: 'flex-start' }} onClick={prepare}>Préparer un nouvel entraînement avec cette configuration</button>
    <span className="muted" style={{ fontSize: 13 }}>Cette action ouvre l'assistant pré-rempli ; elle ne déclenche aucun job.</span>
  </div>;
}

function Artifacts({ run }: { run: MlRun }) {
  const list = useArtifacts(run.run_id);
  if (list.loading) return <Loading what="Liste des artefacts MLflow" />;
  if (list.error) return <Unavailable tone="red">{list.error}</Unavailable>;
  if (!list.data?.length) return <Unavailable tone="grey">Aucun artefact pour ce run.</Unavailable>;
  return <table className="tf-table"><thead><tr><th>Artefact</th><th>Taille</th><th /></tr></thead><tbody>{list.data.map((a) => (
    <tr key={a.path} style={{ cursor: 'default' }}><td>{a.path}</td><td>{a.size != null ? `${(a.size / 1024).toFixed(1).replace('.', ',')} Ko` : '—'}</td>
      <td>{/\.(json|csv|md|ya?ml|txt|png|onnx|pt)$/i.test(a.path) ? <a href={artifactUrl(run.run_id, a.path)} target="_blank" rel="noreferrer">Ouvrir / télécharger</a> : <span className="muted">consultation dans MLflow</span>}</td></tr>))}</tbody></table>;
}

function Logs({ id }: { id: number }) {
  const logs = useLogs(id);
  if (logs.loading) return <Loading what="Lecture des logs Databricks" />;
  if (logs.error) return <Unavailable tone="red">{logs.error}</Unavailable>;
  const l = logs.data;
  return <div className="col" style={{ gap: 10 }}>
    {l?.run_page_url && <a href={l.run_page_url} target="_blank" rel="noreferrer">Ouvrir l'exécution dans Databricks ↗</a>}
    {l?.state && <span className="muted">{l.state}</span>}
    {l?.tasks.map((t) => <div key={t.task} className="tf-box"><b>Tâche {t.task}</b>{t.error && <Unavailable tone="red">{t.error}</Unavailable>}
      {t.logs ? <pre className="tf-pre">{t.logs}</pre> : <span className="muted">Logs non récupérables par l'API : utiliser le lien Databricks.</span>}</div>)}
  </div>;
}
