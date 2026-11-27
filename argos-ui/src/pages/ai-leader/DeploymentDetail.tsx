import { LIFECYCLE_READ_ONLY, type DeploymentOperation } from '../../api/deployment';
import type { ModelStatus } from '../../api/mlops';
import { Badge, KV, LinkButton, Technical, Unavailable } from './common';
import type { Target } from './Deployment';
import { OperationBadge } from './DeploymentStatus';
import { dateTime } from './metrics';
import { Chip } from './ui';

export default function DeploymentDetail({ target, operations, statuses, onClose, onOperation, onNew, onRegistry }: {
  target: Target; operations: DeploymentOperation[]; statuses: ModelStatus[];
  onClose: () => void; onOperation: (id: string) => void; onNew: () => void; onRegistry: (id: string) => void;
}) {
  const cloud = target.kind === 'Cloud';
  const entity = cloud ? target.endpoint.served[0] : null;
  const status = cloud ? statuses.find((item) => item.model_id === target.model?.id) : null;
  const related = cloud ? operations.filter((operation) => operation.endpoint === target.endpoint.name) : [];
  return <section className="card dataset-detail lifecycle-detail col" style={{ gap: 14 }}>
    <header className="between" style={{ gap: 10 }}><div className="col" style={{ gap: 4 }}>
      <h2 className="h2">{cloud ? target.endpoint.name : target.station.name}</h2>
      <span className="muted">{cloud ? 'Databricks Model Serving · Cloud' : `${target.station.station_id} · ${target.station.cell} · Edge`}</span></div>
      <button className="btn btn-ghost" aria-label="Fermer le détail" onClick={onClose}>✕</button></header>
    <div className="row lifecycle-states"><Chip tone={cloud ? target.endpoint.ready === 'READY' ? 'green' : 'amber' : target.station.online ? 'green' : 'amber'}>
      {cloud ? target.endpoint.ready === 'READY' ? 'Endpoint prêt' : target.endpoint.ready ?? 'État inconnu' : target.station.online ? 'Poste en ligne' : 'Poste hors ligne'}</Chip>
      <Chip tone="blue">{cloud ? 'Serving Cloud' : 'Lecture Edge seule'}</Chip></div>
    {cloud ? <>
      <div className="dataset-mini-kpis">
        <Fact label="Modèle servi" value={target.model?.display_name ?? entity?.model ?? '—'} />
        <Fact label="Version active" value={entity?.version ? `v${entity.version}` : '—'} />
        <Fact label="Compute" value={entity?.workload_size ?? '—'} />
        <Fact label="Scale to zero" value={entity?.scale_to_zero == null ? '—' : entity.scale_to_zero ? 'Activé' : 'Désactivé'} />
      </div>
      <div className="row lifecycle-states">
        <Chip tone={entity?.deployment === 'DEPLOYMENT_READY' ? 'green' : 'amber'}>{entity?.deployment === 'DEPLOYMENT_READY' ? 'Configuration déployée et prête' : entity?.deployment ?? 'Déploiement non vérifié'}</Chip>
        <Chip tone="grey">Inférence non testée par DBX-06B</Chip>
        {status?.aliases.champion && <Chip tone="blue">Champion UC : v{status.aliases.champion}</Chip>}
        {entity?.version && <Chip tone={status?.versions.find((v) => v.version.version === entity.version)?.approved ? 'green' : 'amber'}>
          Version servie {status?.versions.find((v) => v.version.version === entity.version)?.approved ? 'approuvée' : 'non approuvée'}</Chip>}
      </div>
      {target.endpoint.pending_versions.length > 0 && <Unavailable>Mise à jour distante en cours vers v{target.endpoint.pending_versions.join(', v')}.</Unavailable>}
      <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
        <button className="btn btn-primary" disabled={LIFECYCLE_READ_ONLY || target.endpoint.name !== 'argos-quality-poc'}
          title={target.endpoint.name === 'argos-quality-poc' ? 'Préparer avec contrôles distants directs' : 'Cible hors du périmètre de mutation DBX-06B'} onClick={onNew}>Nouveau déploiement</button>
        {target.model && <LinkButton onClick={() => onRegistry(target.model!.id)}>Voir les versions</LinkButton>}
      </div>
      <Technical><KV k="config_update" v={target.endpoint.config_update ?? '—'} /><KV k="Entité" v={entity?.name ?? '—'} />
        <KV k="Modèle UC" v={entity?.model ?? '—'} /></Technical>
      <h3>Opérations sur cette cible</h3>
      {related.length === 0 && <Unavailable tone="grey">Aucune opération HOVIS enregistrée. L’endpoint existant ne constitue pas un historique HOVIS.</Unavailable>}
      {related.map((operation) => <button key={operation.operation_id} className="lifecycle-operation-row"
        onClick={() => onOperation(operation.operation_id)}><span>{dateTime(operation.created_at)}</span>
        <b>{operation.kind === 'rollback' ? 'Rollback' : 'Déploiement'} v{operation.previous_version} → v{operation.version}</b>
        <OperationBadge operation={operation} /></button>)}
    </> : <>
      <Unavailable tone="grey">Statuts provenant des événements Edge déjà reçus par le Core. Cette page ne distribue aucun modèle au poste.</Unavailable>
      <div className="dataset-mini-kpis"><Fact label="Poste" value={target.station.station_id} />
        <Fact label="Dernière présence" value={dateTime(target.station.last_seen_at)} />
        <Fact label="Source" value={target.station.simulated ? 'Simulation' : 'Edge'} /></div>
      <h3>Modèles locaux signalés</h3>
      {target.station.models.length === 0 && <Unavailable tone="grey">Aucun modèle local signalé par ce poste.</Unavailable>}
      {target.station.models.map((model, index) => <div key={`${model.use_case}-${index}`} className="lifecycle-event">
        <div className="row lifecycle-states"><Badge tone={model.status === 'loaded' ? 'green' : model.status === 'failed' ? 'red' : 'amber'}>{({ loaded: 'chargé', loading: 'chargement', failed: 'échec', absent: 'absent' } as const)[model.status]}</Badge>
          <b>{model.use_case}</b></div>
        <span>{model.model ? `${model.model.registered_model} · v${model.model.version}` : 'Référence de registre non disponible'}</span>
        {model.loaded_at && <small>Chargé le {dateTime(model.loaded_at)}</small>}{model.error && <small>Erreur : {model.error}</small>}
      </div>)}
    </>}
  </section>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="dataset-mini"><span className="muted">{label}</span><b>{value}</b></div>;
}
