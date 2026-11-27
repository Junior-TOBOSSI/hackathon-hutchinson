import { useEffect, useRef, useState } from 'react';
import { deploymentApi, LIFECYCLE_READ_ONLY, type DeploymentOperation } from '../../api/deployment';
import type { EndpointInfo, ModelStatus } from '../../api/mlops';
import { KV, Loading, Technical, Unavailable } from './common';
import { useStore } from './data';
import { useDeploymentEvents, useDeploymentOperation } from './lifecycleData';
import { dateTime } from './metrics';
import { OperationBadge, operationStatusLabel } from './DeploymentStatus';
import { Chip } from './ui';

const OPEN = ['prepared', 'requesting', 'updating', 'verifying', 'uncertain'];

export default function OperationPanel({ id, initial, statuses, endpoints, onClose, onRollback }: {
  id: string; initial: DeploymentOperation | null; statuses: ModelStatus[]; endpoints: EndpointInfo[];
  onClose: () => void; onRollback: (operation: DeploymentOperation) => void;
}) {
  const store = useStore();
  const resource = useDeploymentOperation(id);
  const events = useDeploymentEvents(id);
  const operation = resource.data ?? initial;
  const previousStatus = useRef<string | null>(initial?.status ?? null);
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!operation || !OPEN.includes(operation.status)) return;
    const timer = window.setInterval(() => store.invalidate(`deployment-operation:${id}`, `deployment-events:${id}`), 5000);
    return () => window.clearInterval(timer);
  }, [id, operation?.status, store]);
  useEffect(() => {
    if (!operation) return;
    const transitioned = previousStatus.current && OPEN.includes(previousStatus.current)
      && !OPEN.includes(operation.status);
    previousStatus.current = operation.status;
    if (transitioned) store.invalidate('deployment-history', 'endpoints', 'statuses');
  }, [operation?.status, store]);
  if (resource.loading && !operation) return <Loading what="Suivi de l’opération" />;
  if (resource.error && !operation) return <Unavailable tone="red">{resource.error}</Unavailable>;
  if (!operation) return null;
  const eligibleRollback = operation.kind === 'deploy' && operation.status === 'succeeded'
    && endpoints.some((endpoint) => endpoint.name === operation.endpoint
      && endpoint.served.some((entity) => entity.version === operation.version))
    && statuses.some((status) => status.model_id === operation.model_id
      && status.versions.some((version) => version.version.version === operation.previous_version && version.approved));
  const submitPrepared = async () => {
    if (operation.status !== 'prepared' || confirmation !== operation.confirmation) return;
    setBusy(true); setError('');
    try { await deploymentApi.confirm(id, confirmation); store.invalidate(`deployment-operation:${id}`, `deployment-events:${id}`, 'deployment-history'); }
    catch (cause) { setError(String(cause)); } finally { setBusy(false); }
  };
  return <section className="card lifecycle-operation-panel col" style={{ gap: 14 }}>
    <header className="between" style={{ gap: 10 }}><div className="col" style={{ gap: 3 }}>
      <h2 className="h2">Suivi · {operation.kind === 'rollback' ? 'rollback' : 'déploiement'}</h2>
      <span className="muted">{operation.operation_id}</span></div>
      <div className="row" style={{ gap: 8 }}><OperationBadge operation={operation} /><button className="btn btn-ghost" aria-label="Fermer le suivi" onClick={onClose}>✕</button></div></header>
    {resource.staleError && <Unavailable>Dernière vérification distante en échec : {resource.staleError}</Unavailable>}
    <div className="dataset-mini-kpis">
      <Fact label="Modèle" value={operation.model_id} /><Fact label="Cible" value={operation.endpoint} />
      <Fact label="Version précédente" value={`v${operation.previous_version}`} /><Fact label="Version demandée" value={`v${operation.version}`} />
      <Fact label="Version active vérifiée" value={operation.verification?.active_version ? `v${operation.verification.active_version}` : 'Non vérifiée'} />
      <Fact label="Auteur déclaré" value={operation.author_declared} />
    </div>
    <div className="row lifecycle-states"><Chip tone={operation.verification?.ready === 'READY' && operation.verification?.deployment === 'DEPLOYMENT_READY' ? 'green' : 'grey'}>
      Endpoint {operation.verification?.ready === 'READY' ? 'prêt' : 'non vérifié'}</Chip>
      <Chip tone="grey">Inférence {operation.inference_tested ? 'testée' : 'non testée'}</Chip>
      <Chip tone="blue">Alias champion inchangé par cette opération</Chip></div>
    {operation.status === 'uncertain' && <Unavailable>Résultat distant incertain : une nouvelle mutation ne doit pas être envoyée. Le suivi relit Serving jusqu’à résolution ou intervention humaine.</Unavailable>}
    {operation.status === 'failed' && <Unavailable tone="red">Mise à jour échouée. Cela ne signifie pas qu’un rollback ARGOS a eu lieu.</Unavailable>}
    {operation.error && <Unavailable tone="red">Erreur : {operation.error}</Unavailable>}
    <div className="col" style={{ gap: 3 }}><b>Motif</b><span>{operation.reason}</span></div>
    <div className="row dataset-detail-meta"><span>Création : <b>{dateTime(operation.created_at)}</b></span>
      <span>Demande : <b>{dateTime(operation.submitted_at)}</b></span>
      <span>Fin : <b>{dateTime(operation.completed_at)}</b></span>
      <span>Dernière vérification : <b>{dateTime(String(operation.verification?.checked_at ?? ''))}</b></span></div>
    <h3>Chronologie</h3>
    {events.loading && <Loading what="Transitions" />}{events.error && <Unavailable tone="red">{events.error}</Unavailable>}
    <ol className="lifecycle-timeline">{events.data?.map((event, index) => <li key={`${event.at}-${index}`} className={`lifecycle-status-${event.status}`}>
      <b>{operationStatusLabel(event.status)}</b><span>{dateTime(event.at)}</span>{event.note && <small>{event.note}</small>}</li>)}</ol>
    {operation.status === 'prepared' && <div className="lifecycle-form"><b>Reprendre la confirmation préparée</b>
      <span>Vérifiez les configurations ci-dessous. La confirmation expire le {dateTime(operation.expires_at)}.</span>
      <label>Recopiez « {operation.confirmation} »<input className="input" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
      {error && <Unavailable tone="red">{error}</Unavailable>}
      <button className="btn btn-primary" disabled={LIFECYCLE_READ_ONLY || busy || confirmation !== operation.confirmation} onClick={submitPrepared}>Confirmer la demande Serving</button></div>}
    {eligibleRollback && <button className="btn btn-ghost" disabled={LIFECYCLE_READ_ONLY} onClick={() => onRollback(operation)}>Préparer un rollback vers v{operation.previous_version}</button>}
    <Technical title="Configurations et vérification"><KV k="Configuration précédente" v={<pre className="lifecycle-config">{JSON.stringify(operation.previous_config, null, 2)}</pre>} />
      <KV k="Configuration demandée" v={<pre className="lifecycle-config">{JSON.stringify(operation.requested_config, null, 2)}</pre>} />
      <KV k="Vérification" v={<pre className="lifecycle-config">{JSON.stringify(operation.verification, null, 2)}</pre>} /></Technical>
  </section>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="dataset-mini"><span className="muted">{label}</span><b>{value}</b></div>;
}
