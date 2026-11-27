import { useState } from 'react';
import { deploymentApi, LIFECYCLE_READ_ONLY, type DeploymentOperation } from '../../api/deployment';
import type { EndpointInfo, ManagedModel, ModelStatus } from '../../api/mlops';
import { Loading, Unavailable } from './common';
import { dateTime } from './metrics';
import { Chip, SelectField } from './ui';

const SUPPORTED_ENDPOINT = 'argos-quality-poc'; // DBX-06B allowlist; no other remote target is offered.

export default function DeploymentWizard({ models, statuses, endpoints, initialEndpoint, rollbackSource, onClose, onSubmitted }: {
  models: ManagedModel[]; statuses: ModelStatus[]; endpoints: EndpointInfo[];
  initialEndpoint: string | null; rollbackSource: DeploymentOperation | null;
  onClose: () => void; onSubmitted: (operation: DeploymentOperation) => void;
}) {
  const [modelId, setModelId] = useState(rollbackSource?.model_id ?? '');
  const [version, setVersion] = useState(rollbackSource?.previous_version ?? '');
  const [endpointName, setEndpointName] = useState(rollbackSource?.endpoint ?? initialEndpoint ?? '');
  const [reason, setReason] = useState('');
  const [author, setAuthor] = useState('');
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [prepared, setPrepared] = useState<DeploymentOperation | null>(null);
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const eligible = models.filter((model) => model.endpoint === SUPPORTED_ENDPOINT
    && endpoints.some((endpoint) => endpoint.name === model.endpoint));
  const model = eligible.find((item) => item.id === modelId);
  const status = statuses.find((item) => item.model_id === modelId);
  const approved = status?.versions.filter((item) => item.approved && /^\d+$/.test(item.version.version)) ?? [];
  const endpoint = endpoints.find((item) => item.name === endpointName);
  const canPrepare = reason.trim().length >= 3 && !!author.trim() && !!model && !!endpoint
    && approved.some((item) => item.version.version === version);
  const prepare = async () => {
    if (!canPrepare) return;
    setBusy(true); setError('');
    try {
      const operation = rollbackSource
        ? await deploymentApi.prepareRollback(rollbackSource.operation_id, reason.trim(), author.trim())
        : await deploymentApi.prepare({ model_id: modelId, version, endpoint: endpointName,
          reason: reason.trim(), author_declared: author.trim(), role_declared: 'ai_leader' });
      setPrepared(operation); setStep(2);
    } catch (cause) { setError(String(cause)); } finally { setBusy(false); }
  };
  const confirm = async () => {
    if (!prepared || confirmation !== prepared.confirmation) return;
    setBusy(true); setError('');
    try { onSubmitted(await deploymentApi.confirm(prepared.operation_id, confirmation)); }
    catch (cause) { setError(String(cause)); } finally { setBusy(false); }
  };
  return <div className="lifecycle-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="card lifecycle-wizard col" role="dialog" aria-modal="true" aria-label={rollbackSource ? 'Préparer un rollback' : 'Nouveau déploiement'}>
      <header className="between" style={{ gap: 12 }}><div className="col" style={{ gap: 3 }}><h2 className="h2">{rollbackSource ? 'Rollback explicite' : 'Nouveau déploiement'}</h2>
        <span className="muted">{step}. {step === 1 ? 'Configuration' : step === 2 ? 'Vérification des conditions' : 'Confirmation'}</span></div>
        <button className="btn btn-ghost" aria-label="Fermer l’assistant" onClick={onClose}>✕</button></header>
      <div className="lifecycle-steps"><span className={step >= 1 ? 'active' : ''}>1 · Configuration</span>
        <span className={step >= 2 ? 'active' : ''}>2 · Vérification</span><span className={step >= 3 ? 'active' : ''}>3 · Confirmation</span></div>
      {step === 1 && <div className="lifecycle-form">
        {rollbackSource && <Unavailable tone="grey">Retour vers v{rollbackSource.previous_version} depuis le déploiement vérifié {rollbackSource.operation_id}. L’alias champion ne changera pas.</Unavailable>}
        <div className="lifecycle-form-grid"><label>Modèle
          {rollbackSource ? <input className="input" disabled value={model?.display_name ?? modelId} />
            : <SelectField label="Modèle à déployer" icon="none" value={modelId} onChange={(id) => {
              setModelId(id); setVersion(''); setEndpointName(eligible.find((item) => item.id === id)?.endpoint ?? '');
            }} allLabel="Sélectionner un modèle" options={eligible.map((item) => [item.id, item.display_name])} />}
        </label><label>Version numérique approuvée
          {rollbackSource ? <input className="input" disabled value={`v${version}`} />
            : <SelectField label="Version numérique approuvée" icon="none" value={version} onChange={setVersion}
              allLabel="Sélectionner une version" options={approved.map((item) => [item.version.version, `v${item.version.version}`])} />}
        </label><label>Cible compatible
          {rollbackSource ? <input className="input" disabled value={endpointName} />
            : <SelectField label="Cible compatible" icon="none" value={endpointName} onChange={setEndpointName}
              allLabel="Sélectionner une cible" options={model?.endpoint && endpoints.some((item) => item.name === model.endpoint)
                ? [[model.endpoint, model.endpoint]] : []} />}
        </label><label>Auteur déclaré<input className="input" value={author} onChange={(event) => setAuthor(event.target.value)} maxLength={100} placeholder="Nom affiché" /></label></div>
        <label>Motif<textarea className="input lifecycle-textarea" value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500} placeholder="Justification du changement" /></label>
        <span className="muted">Identité authentifiée indisponible · aucune cible Edge n’est proposée.</span>
        {!eligible.length && <Unavailable tone="grey">Aucune cible Cloud autorisée par DBX-06B n’est disponible.</Unavailable>}
        {error && <Unavailable tone="red">{error}</Unavailable>}
        <button className="btn btn-primary" disabled={LIFECYCLE_READ_ONLY || busy || !canPrepare} onClick={prepare}>{busy ? 'Contrôles distants…' : 'Vérifier les conditions'}</button>
      </div>}
      {prepared && step === 2 && <div className="col" style={{ gap: 12 }}>
        <Unavailable tone="grey">Préparation enregistrée le {dateTime(prepared.created_at)}. La confirmation expire le {dateTime(prepared.expires_at)}.</Unavailable>
        <div className="dataset-mini-kpis"><Fact label="Cible" value={prepared.endpoint} /><Fact label="Modèle UC" value={prepared.registered_model} />
          <Fact label="Version actuelle" value={`v${prepared.previous_version}`} /><Fact label="Version demandée" value={`v${prepared.version}`} /></div>
        <div className="row lifecycle-states"><Chip tone="green">Version approuvée relue dans UC</Chip><Chip tone="green">Endpoint prêt, sans mise à jour concurrente</Chip>
          <Chip tone="green">Topologie à entité unique préservée</Chip></div>
        <h3>Configuration préservée</h3><pre className="lifecycle-config">{JSON.stringify(prepared.previous_config, null, 2)}</pre>
        <h3>Configuration demandée</h3><pre className="lifecycle-config">{JSON.stringify(prepared.requested_config, null, 2)}</pre>
        <Unavailable>La préparation ne déploie rien. Les contrôles seront relus directement dans Databricks à la confirmation.</Unavailable>
        <button className="btn btn-primary" onClick={() => setStep(3)}>Passer à la confirmation</button>
      </div>}
      {prepared && step === 3 && <div className="lifecycle-form">
        <b>{prepared.kind === 'rollback' ? 'Confirmer le rollback' : 'Confirmer le déploiement'} vers v{prepared.version}</b>
        <span>De v{prepared.previous_version} vers v{prepared.version} sur <b>{prepared.endpoint}</b>.</span>
        <Unavailable>Le changement Serving est une mutation distante. Une réponse à la demande ne prouve pas que la version est prête ; le suivi vérifiera l’état réel.</Unavailable>
        <label>Recopiez exactement « {prepared.confirmation} »
          <input className="input" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" /></label>
        {error && <Unavailable tone="red">{error}</Unavailable>}
        <div className="row" style={{ gap: 8 }}><button className="btn btn-ghost" onClick={() => setStep(2)}>Retour</button>
          <button className="btn btn-primary" disabled={LIFECYCLE_READ_ONLY || busy || confirmation !== prepared.confirmation} onClick={confirm}>
            {busy ? 'Envoi…' : 'Soumettre à Databricks Serving'}</button></div>
      </div>}
      {busy && <Loading what="Opération en cours" />}
      {prepared && <span className="muted" style={{ fontSize: 12 }}>Une préparation fermée reste dans le journal HOVIS jusqu’à expiration ou confirmation ; aucune mutation distante n’est lancée par la fermeture.</span>}
    </section>
  </div>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="dataset-mini"><span className="muted">{label}</span><b>{value}</b></div>;
}
