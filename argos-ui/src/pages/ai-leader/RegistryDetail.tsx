import { useEffect, useState } from 'react';
import { deploymentApi, LIFECYCLE_READ_ONLY, type DecisionValue } from '../../api/deployment';
import { mlops, type ManagedModel, type ModelStatus, type RunSummary, type VersionStatus } from '../../api/mlops';
import { GroupedBars } from './charts';
import { Badge, KV, LinkButton, Loading, Technical, Unavailable, useNav } from './common';
import { errText, useRun, useRunMap, useStore } from './data';
import { useDecisionHistory } from './lifecycleData';
import { comparableMetricRows, comparability, confusion, decisionOf, metricValue, type ModelRow } from './lifecycleCatalog';
import { dateTime, format, groupBySplit, SPLIT_LABEL } from './metrics';
import { Chip, fr, SelectField } from './ui';

const TABS = ['Vue d’ensemble', 'Versions', 'Comparaison', 'Évaluation', 'Lignage', 'Artefacts', 'Décisions'] as const;
type Tab = typeof TABS[number];
const COLORS = ['var(--navy)', 'var(--primary-light)', 'var(--cat-qualite)', 'var(--cat-rythme)'];
const decisionLabel = (version: VersionStatus, latest?: boolean) => decisionOf(version) === 'approved' ? 'Approuvée'
  : decisionOf(version) === 'rejected' ? 'Refusée'
    : latest && version.aliases.length === 0 ? 'Dernier candidat · sans alias' : 'Sans décision';

export default function RegistryDetail({ row, onClose, onMessage }: {
  row: ModelRow; onClose: () => void; onMessage: (message: string) => void;
}) {
  const { model, status } = row;
  const [tab, setTab] = useState<Tab>('Vue d’ensemble');
  const [version, setVersion] = useState<string | null>(row.latest?.version.version ?? null);
  useEffect(() => {
    if (!version && row.latest) setVersion(row.latest.version.version);
  }, [row.latest, version]);
  const selected = status?.versions.find((item) => item.version.version === version) ?? null;
  const run = useRun(selected?.version.run_id ?? null);
  const datasetId = run.data?.params.dataset_id ?? run.data?.params.dataset_family_id ?? null;
  const datasetVersion = run.data?.params.dataset_version ?? selected?.version.tags.argos_dataset_version ?? null;
  const { go } = useNav();
  return <section className="card dataset-detail lifecycle-detail col" style={{ gap: 14 }}>
    <header className="between" style={{ gap: 10 }}><div className="col" style={{ gap: 4 }}>
      <h2 className="h2">{model.display_name}</h2><span className="muted">{model.uc_name}</span></div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {model.synthetic && <Badge tone="amber">Démo synthétique</Badge>}
        <button className="btn btn-ghost" aria-label="Fermer le détail" onClick={onClose}>✕</button>
      </div></header>
    <div className="row dataset-detail-meta"><span>Usage : <b>{fr(model.argos_use_case)}</b></span>
      <span>Tâche : <b>{row.task ?? 'non renseignée'}</b></span>
      <span>Architecture : <b>{row.architecture ?? 'non renseignée'}</b></span>
      <span>Dernière activité : <b>{dateTime(row.activity)}</b></span></div>
    <div className="row lifecycle-states">
      <Chip tone={selected ? decisionOf(selected) === 'approved' ? 'green' : decisionOf(selected) === 'rejected' ? 'red' : 'grey' : 'grey'}>Approbation {version ? `v${version}` : ''} : {selected ? decisionLabel(selected, row.latest?.version.version === version) : '—'}</Chip>
      <Chip tone="blue">Alias champion : {row.champion ? `v${row.champion}` : 'aucun'}</Chip>
      <Chip tone="amber">Servie : {row.served ? `v${row.served}` : 'aucune'}</Chip>
    </div>
    <nav className="dataset-tabs" aria-label="Détail du modèle">{TABS.map((name) =>
      <button key={name} className={tab === name ? 'active' : ''} onClick={() => setTab(name)}>{name}</button>)}</nav>
    {tab === 'Vue d’ensemble' && <div className="col" style={{ gap: 14 }}>
      <div className="dataset-mini-kpis"><Mini label="Versions" value={row.versions} /><Mini label="En attente" value={row.pending} />
        <Mini label="Champion" value={row.champion ? `v${row.champion}` : '—'} /><Mini label="Servie" value={row.served ? `v${row.served}` : '—'} /></div>
      <Unavailable tone="grey">Les métriques de run sont mesurées hors ligne ; elles ne prouvent pas la performance du poste industriel.</Unavailable>
      {selected && <><VersionPicker versions={status?.versions ?? []} value={version} onChange={setVersion} />
        <div className="dataset-mini-kpis"><Mini label="Version" value={`v${version}`} /><Mini label="Date UC" value={dateTime(selected.version.created_at)} />
          <Mini label="Dataset" value={run.data?.params.dataset_version ?? selected.version.tags.argos_dataset_version ?? 'Non renseigné'} />
          <Mini label="Run" value={run.data?.run_name ?? selected.version.run_id ?? 'Non renseigné'} /></div>
        {run.loading && <Loading what="Métriques du run" />}{run.error && <Unavailable tone="red">{run.error}</Unavailable>}
        {run.data && <MetricsBlock run={run.data} compact />}</>}
    </div>}
    {tab === 'Versions' && <div className="col" style={{ gap: 10 }}>
      {(status?.versions ?? []).length === 0 && <Unavailable tone="grey">Aucune version enregistrée dans Unity Catalog.</Unavailable>}
      {[...(status?.versions ?? [])].sort((a, b) => Number(b.version.version) - Number(a.version.version)).map((item) =>
        <button key={item.version.version} className={`dataset-version${version === item.version.version ? ' selected' : ''}`}
          onClick={() => { setVersion(item.version.version); setTab('Vue d’ensemble'); }}>
          <b>v{item.version.version}</b><Chip tone={decisionOf(item) === 'approved' ? 'green' : decisionOf(item) === 'rejected' ? 'red' : 'grey'}>{decisionLabel(item, row.latest?.version.version === item.version.version)}</Chip>
          {item.aliases.map((alias) => <Chip key={alias} tone="blue">{alias}</Chip>)}
          {item.served_by.length > 0 && <Chip tone="amber">servie par {item.served_by.join(', ')}</Chip>}
          <span className="muted">{dateTime(item.version.created_at)}</span>
        </button>)}
    </div>}
    {tab === 'Comparaison' && <ComparisonTab versions={status?.versions ?? []} />}
    {tab === 'Évaluation' && <div className="col" style={{ gap: 12 }}><VersionPicker versions={status?.versions ?? []} value={version} onChange={setVersion} />
      {run.loading && <Loading what="Évaluation MLflow" />}{run.error && <Unavailable tone="red">{run.error}</Unavailable>}
      {run.data ? <><MetricsBlock run={run.data} /><ConfusionMatrix run={run.data} /></>
        : !run.loading && <Unavailable tone="grey">Aucun run lié à cette version : évaluation indisponible.</Unavailable>}</div>}
    {tab === 'Lignage' && <div className="col" style={{ gap: 10 }}><VersionPicker versions={status?.versions ?? []} value={version} onChange={setVersion} />
      <Mini label="Run MLflow" value={selected?.version.run_id ?? 'Non renseigné'} />
      <Mini label="Dataset déclaré" value={datasetVersion ?? 'Non renseigné'} />
      {selected?.version.run_id && <a className="lifecycle-link" href={`/api/mlops/runs/${encodeURIComponent(selected.version.run_id)}`} target="_blank" rel="noreferrer">Ouvrir les données du run ↗</a>}
      {datasetId ? <a className="lifecycle-link" href={`/ai-leader?section=datasets&dataset=${encodeURIComponent(datasetId)}${datasetVersion ? `&version=${encodeURIComponent(datasetVersion)}` : ''}`}>
        Ouvrir le dataset utilisé ↗</a> : <LinkButton onClick={() => go('datasets', null)}>Ouvrir le catalogue des datasets (identifiant non déclaré)</LinkButton>}
      {run.data && <Technical title="Paramètres du run">{Object.entries(run.data.params).map(([key, value]) => <KV key={key} k={key} v={value} />)}</Technical>}
    </div>}
    {tab === 'Artefacts' && <div className="col" style={{ gap: 10 }}><VersionPicker versions={status?.versions ?? []} value={version} onChange={setVersion} />
      <KV k="Source du modèle" v={selected?.version.source || 'Non renseignée'} />
      <KV k="Logged model ID" v={selected?.version.model_id ?? 'Non renseigné'} />
      <KV k="Run MLflow" v={selected?.version.run_id ?? 'Non renseigné'} />
      <Unavailable tone="grey">La liste des fichiers et leur contenu ne sont pas exposés par l’API actuelle. Aucune copie d’artefact n’est créée ici.</Unavailable>
      {selected && <Technical title="Tags Unity Catalog">{Object.entries(selected.version.tags).map(([key, value]) => <KV key={key} k={key} v={value} />)}</Technical>}
    </div>}
    {tab === 'Décisions' && <DecisionTab model={model} status={status} selected={selected} version={version}
      onVersion={setVersion} onMessage={onMessage} />}
  </section>;
}

function Mini({ label, value }: { label: string; value: string | number }) {
  return <div className="dataset-mini"><span className="muted">{label}</span><b>{value}</b></div>;
}

function VersionPicker({ versions, value, onChange }: { versions: VersionStatus[]; value: string | null; onChange: (version: string) => void }) {
  return versions.length ? <div style={{ maxWidth: 280 }}><SelectField label="Version" icon="none" value={value ?? ''}
    onChange={onChange} options={[...versions].sort((a, b) => Number(b.version.version) - Number(a.version.version))
      .map((item) => [item.version.version, `Version ${item.version.version}`])} /></div>
    : <Unavailable tone="grey">Aucune version disponible.</Unavailable>;
}

/** Reused by Training Factory: available MLflow metrics only, grouped by their true split. */
export function MetricsBlock({ run, compact }: { run: RunSummary; compact?: boolean }) {
  const groups = groupBySplit(run.metrics).filter((group) => !compact || group.split === 'validation' || group.split === 'test');
  if (!groups.length) return <Unavailable tone="grey">Aucune métrique enregistrée pour ce run.</Unavailable>;
  return <div className="col" style={{ gap: 12 }}>{groups.map((group) =>
    <div key={group.split} className="col" style={{ gap: 6 }}><b>{SPLIT_LABEL[group.split]}</b>
      <div className="dataset-mini-kpis">{group.items.map(({ info, value }) => <Mini key={info.key} label={info.label} value={format(info, value)} />)}</div>
    </div>)}</div>;
}

function ComparisonTab({ versions }: { versions: VersionStatus[] }) {
  const [split, setSplit] = useState<'validation' | 'test'>('validation');
  const ids = versions.map((version) => version.version.run_id).filter((id): id is string => !!id);
  const resource = useRunMap(ids);
  if (resource.loading) return <Loading what="Runs à comparer" />;
  if (resource.error) return <Unavailable tone="red">{resource.error}</Unavailable>;
  const rows = versions.filter((version) => version.version.run_id && resource.data?.[version.version.run_id])
    .map((version) => ({ version, run: resource.data?.[version.version.run_id as string] as RunSummary }));
  const available = comparableMetricRows(rows.map((row) => row.run), split)
    .filter((metric) => rows.some((row) => metricValue(row.run, split, metric.bases) != null));
  const groups = available.filter((metric) => metric.unit === 'percent').map((metric) => ({ label: metric.label,
    bars: rows.flatMap((row, index) => {
      const value = metricValue(row.run, split, metric.bases);
      return value == null ? [] : [{ label: `v${row.version.version.version}`, value, color: COLORS[index % COLORS.length] }];
    }),
  }));
  const comparison = comparability(rows.map((row) => row.run));
  const comparable = comparison.startsWith('Même');
  return <div className="col" style={{ gap: 14 }}>
    <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}><b>Split :</b>
      {(['validation', 'test'] as const).map((item) => <button key={item} className={`btn ${split === item ? 'btn-dark' : 'btn-ghost'}`}
        onClick={() => setSplit(item)}>{item === 'validation' ? 'Validation' : 'Test'}</button>)}</div>
    <Unavailable tone={comparable ? 'grey' : 'amber'}>{comparison}</Unavailable>
    {available.length ? <><div className="dataset-table-wrap"><table className="dataset-table"><thead><tr><th>Métrique</th>
      {rows.map((row) => <th key={row.version.version.version}>v{row.version.version.version}</th>)}
      </tr></thead><tbody>{available.map((metric) => <tr key={metric.label}><td><b>{metric.label}</b></td>
        {rows.map((row) => { const value = metricValue(row.run, split, metric.bases);
          return <td key={row.version.version.version}>{value == null ? '—' : metric.unit === 'percent' ? `${(value * 100).toFixed(1).replace('.', ',')} %` : `${value.toLocaleString('fr-FR')}${metric.unit === 'ms' ? ' ms' : ''}`}</td>;
        })}</tr>)}</tbody></table></div>
      {comparable && groups.length > 0 && <GroupedBars groups={groups} max={1} format={(value) => `${(value * 100).toFixed(1).replace('.', ',')} %`} />}</>
      : <Unavailable tone="grey">Aucune métrique comparable sur ce split.</Unavailable>}
  </div>;
}

function ConfusionMatrix({ run }: { run: RunSummary }) {
  const [split, setSplit] = useState<'validation' | 'test'>('validation');
  const values = confusion(run, split);
  return <div className="col" style={{ gap: 10 }}><div className="row" style={{ gap: 8, flexWrap: 'wrap' }}><b>Matrice de confusion</b>
    <SelectField label="Split de la matrice" icon="none" value={split} onChange={(value) => setSplit(value as typeof split)}
      options={[["validation", "Validation"], ["test", "Test"]]} /></div>
    {values ? <div className="lifecycle-confusion" role="table" aria-label={`Matrice de confusion ${split}`}>
      <span /><b>Prédit négatif</b><b>Prédit positif</b>
      <b>Réel négatif</b><span>{values.tn.toLocaleString('fr-FR')}</span><span>{values.fp.toLocaleString('fr-FR')}</span>
      <b>Réel positif</b><span>{values.fn.toLocaleString('fr-FR')}</span><span>{values.tp.toLocaleString('fr-FR')}</span>
    </div> : <Unavailable tone="grey">Matrice non enregistrée pour ce split (TP, TN, FP et FN nécessaires).</Unavailable>}</div>;
}

function DecisionTab({ model, status, selected, version, onVersion, onMessage }: {
  model: ManagedModel; status: ModelStatus | null; selected: VersionStatus | null; version: string | null;
  onVersion: (version: string) => void; onMessage: (message: string) => void;
}) {
  const { go } = useNav();
  const store = useStore();
  const history = useDecisionHistory(model.id, version);
  const [choice, setChoice] = useState<DecisionValue>('approved');
  const [reason, setReason] = useState('');
  const [author, setAuthor] = useState('');
  const [acknowledge, setAcknowledge] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const served = !!selected?.served_by.length;
  const latestVersion = [...(status?.versions ?? [])].sort((a, b) => Number(b.version.version) - Number(a.version.version))[0]?.version.version;
  const decide = async () => {
    if (!selected || !version || reason.trim().length < 3 || !author.trim()) return;
    if (choice === 'rejected' && served && !acknowledge) { setError('Confirmez que le refus n’arrête pas la version déjà servie.'); return; }
    if (!window.confirm(`${choice === 'approved' ? 'Approuver' : 'Refuser'} v${version} ?\n\nMotif : ${reason.trim()}\n\nCette décision ne modifie ni l’alias champion ni Serving.`)) return;
    setBusy(true); setError('');
    try {
      const result = await deploymentApi.decide(model.id, version, { decision: choice, reason: reason.trim(), author_declared: author.trim(), role_declared: 'ai_leader', acknowledge_served_rejection: acknowledge });
      store.invalidate(`decision-history:${model.id}:${version}`, 'statuses', 'overview');
      onMessage(result.status === 'applied' ? `Décision v${version} enregistrée dans Unity Catalog.` : `Décision v${version} incertaine : vérifiez l’état distant avant toute nouvelle action.`);
      if (result.status === 'applied') setReason('');
    } catch (cause) { setError(errText(cause)); } finally { setBusy(false); }
  };
  const promote = async () => {
    if (!selected || !selected.approved || !version) return;
    if (!window.confirm(`Définir v${version} comme champion ?\n\nSeul l’alias Unity Catalog change. Aucun déploiement Serving ni Edge n’est lancé.`)) return;
    setBusy(true); setError('');
    try { await mlops.promote(model.id, version); store.invalidate('statuses', 'overview'); onMessage(`Alias champion déplacé vers v${version}. La version servie reste indépendante.`); }
    catch (cause) { setError(errText(cause)); } finally { setBusy(false); }
  };
  return <div className="col" style={{ gap: 14 }}>
    <VersionPicker versions={status?.versions ?? []} value={version} onChange={onVersion} />
    {selected && <div className="row lifecycle-states"><Chip tone={decisionOf(selected) === 'approved' ? 'green' : decisionOf(selected) === 'rejected' ? 'red' : 'grey'}>v{version} · {decisionLabel(selected, latestVersion === version)}</Chip>
      <Chip tone="blue">Champion {status?.aliases.champion === version ? `v${version}` : status?.aliases.champion ? `v${status.aliases.champion}` : '—'}</Chip>
      <Chip tone="amber">Serving {served ? `v${version}` : 'autre version / aucun'}</Chip></div>}
    <div className="lifecycle-form">
      <b>Nouvelle décision motivée</b><span className="muted">Auteur et rôle déclarés pour la démonstration · identité authentifiée indisponible.</span>
      <div className="lifecycle-form-grid"><label>Décision<select className="input" value={choice} onChange={(event) => setChoice(event.target.value as DecisionValue)}>
        <option value="approved">Approuver</option><option value="rejected">Refuser</option></select></label>
        <label>Auteur déclaré<input className="input" value={author} onChange={(event) => setAuthor(event.target.value)} maxLength={100} placeholder="Nom affiché" /></label></div>
      <label>Motif<textarea className="input lifecycle-textarea" value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500} placeholder="Justification de la décision" /></label>
      {choice === 'rejected' && served && <label className="row" style={{ gap: 8 }}><input type="checkbox" checked={acknowledge} onChange={(event) => setAcknowledge(event.target.checked)} />
        Je comprends que cette version reste servie et qu’une action Serving distincte sera nécessaire.</label>}
      {error && <Unavailable tone="red">{error}</Unavailable>}
      {LIFECYCLE_READ_ONLY && <Unavailable tone="grey">Recette connectée en lecture seule : décisions et promotions désactivées.</Unavailable>}
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}><button className="btn btn-primary" disabled={LIFECYCLE_READ_ONLY || busy || !selected || reason.trim().length < 3 || !author.trim()} onClick={decide}>
        {busy ? 'En cours…' : 'Confirmer la décision'}</button>
        <button className="btn btn-ghost" disabled={LIFECYCLE_READ_ONLY || busy || !selected?.approved || status?.aliases.champion === version} onClick={promote}>Promouvoir champion</button>
        <LinkButton onClick={() => go('deployment', model.id)}>Voir les cibles</LinkButton></div>
    </div>
    <div className="col" style={{ gap: 8 }}><h3>Historique des décisions</h3>
      {history.loading && <Loading />}{history.error && <Unavailable tone="red">{history.error}</Unavailable>}
      {history.data?.length === 0 && <Unavailable tone="grey">Aucune décision HOVIS enregistrée pour cette version.</Unavailable>}
      {history.data?.map((record) => <div className="lifecycle-event" key={record.decision_id}>
        <Chip tone={record.status === 'uncertain' ? 'amber' : record.decision === 'approved' ? 'green' : 'red'}>{record.decision === 'approved' ? 'Approuvée' : 'Refusée'} · {record.status === 'uncertain' ? 'incertaine' : record.status === 'applied' ? 'appliquée' : 'en cours'}</Chip>
        <b>{dateTime(record.created_at)}</b><span>{record.reason}</span><small>Auteur déclaré : {record.author_declared} · identité vérifiée : indisponible</small>
        {record.requires_serving_action && <small>Version toujours servie : action Serving distincte nécessaire.</small>}
      </div>)}</div>
  </div>;
}
