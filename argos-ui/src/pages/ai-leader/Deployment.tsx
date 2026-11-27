import { useMemo, useState } from 'react';
import { LIFECYCLE_READ_ONLY, type DeploymentOperation, type EdgeStation } from '../../api/deployment';
import type { EndpointInfo, ManagedModel } from '../../api/mlops';
import { Loading, Unavailable, useNav } from './common';
import { useEndpoints, useManaged, useStatuses, useStore } from './data';
import { useDeploymentHistory, useEdgeStations } from './lifecycleData';
import { dateTime } from './metrics';
import DeploymentDetail from './DeploymentDetail';
import { OperationBadge } from './DeploymentStatus';
import DeploymentWizard from './DeploymentWizard';
import OperationPanel from './OperationPanel';
import { Chip, Kpi, SearchField, SelectField } from './ui';
import './datasets/catalog.css';
import './lifecycle.css';

export interface CloudTarget { kind: 'Cloud'; id: string; endpoint: EndpointInfo; model: ManagedModel | null; }
export interface EdgeTarget { kind: 'Edge'; id: string; station: EdgeStation; }
export type Target = CloudTarget | EdgeTarget;
const ACTIVE = ['prepared', 'requesting', 'updating', 'verifying', 'uncertain'];
const ready = (target: Target) => target.kind === 'Cloud'
  ? target.endpoint.ready === 'READY' && target.endpoint.config_update === 'NOT_UPDATING'
    && target.endpoint.served.every((entity) => entity.deployment === 'DEPLOYMENT_READY')
  : target.station.online;

export default function Deployment() {
  const endpoints = useEndpoints();
  const models = useManaged();
  const statuses = useStatuses();
  const history = useDeploymentHistory();
  const edge = useEdgeStations();
  const store = useStore();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [wizard, setWizard] = useState(false);
  const [rollbackSource, setRollbackSource] = useState<DeploymentOperation | null>(null);
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('');
  const [state, setState] = useState('');
  const [tab, setTab] = useState<'Cibles' | 'Historique'>('Cibles');
  const { go } = useNav();
  const targets = useMemo<Target[]>(() => [
    ...(endpoints.data ?? []).filter((endpoint) => (models.data ?? []).some((model) => model.endpoint === endpoint.name))
      .map((endpoint): CloudTarget => ({ kind: 'Cloud', id: `cloud:${endpoint.name}`, endpoint,
        model: (models.data ?? []).find((model) => model.endpoint === endpoint.name) ?? null })),
    ...(edge.data ?? []).map((station): EdgeTarget => ({ kind: 'Edge', id: `edge:${station.station_id}`, station })),
  ], [endpoints.data, models.data, edge.data]);
  const selected = targets.find((target) => target.id === selectedId) ?? null;
  const filtered = targets.filter((target) => (!kind || target.kind === kind)
    && (!state || (state === 'ready' ? ready(target) : !ready(target)))
    && (target.kind === 'Cloud'
      ? `${target.endpoint.name} ${target.model?.display_name ?? ''}`
      : `${target.station.station_id} ${target.station.name} ${target.station.cell}`)
      .toLocaleLowerCase('fr').includes(query.toLocaleLowerCase('fr')));
  const cloud = targets.filter((target): target is CloudTarget => target.kind === 'Cloud');
  const operations = history.data ?? [];
  const count = (value: number) => history.data ? value : '—';
  const selectedOperation = operations.find((operation) => operation.operation_id === operationId) ?? null;
  const openWizard = () => { setRollbackSource(null); setWizard(true); setOperationId(null); };
  const openRollback = (operation: DeploymentOperation) => { setRollbackSource(operation); setWizard(true); setOperationId(null); };

  return <div className="dataset-catalog lifecycle-catalog col" style={{ gap: 14 }}>
    <header className="card dataset-hero"><div><h1 className="h2">Centre de déploiement — Cibles & opérations</h1>
      <p className="muted">Serving Databricks et postes Edge sont deux déploiements distincts.</p>
      <span className="muted lifecycle-fresh">Lecture Serving : {dateTime(endpoints.fetchedAt)}{endpoints.cache === 'stale' ? ' · dernière valeur connue' : ''} · historique HOVIS : {dateTime(history.fetchedAt)}</span></div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}><button className="btn btn-ghost" onClick={() => store.invalidate('endpoints', 'deployment-history', 'deployment-edge-stations')}>Actualiser</button>
        <button className="btn btn-primary" disabled={LIFECYCLE_READ_ONLY} onClick={openWizard}>Nouveau déploiement</button></div></header>
    {LIFECYCLE_READ_ONLY && <Unavailable tone="grey">Recette connectée en lecture seule : aucune mutation Serving, Registry ou Edge n’est accessible depuis cette interface.</Unavailable>}
    {endpoints.error && <Unavailable tone="red">Serving indisponible : {endpoints.error}</Unavailable>}
    {endpoints.staleError && <Unavailable>Dernière lecture Serving en échec : {endpoints.staleError}</Unavailable>}
    {history.error && <Unavailable tone="red">Historique HOVIS indisponible : {history.error}</Unavailable>}
    {edge.error && <Unavailable tone="grey">Statuts Edge non disponibles depuis cette passerelle : {edge.error}. Les cibles Cloud restent consultables.</Unavailable>}
    <div className="dataset-kpis">
      <Kpi icon="monitor" label="Endpoints gérés" value={endpoints.data ? cloud.length : '—'} hint="Périmètre HOVIS" />
      <Kpi icon="check" label="Endpoints prêts" value={endpoints.data ? cloud.filter((target) => ready(target)).length : '—'} tone="green" />
      <Kpi icon="layers" label="Versions servies" value={endpoints.data ? cloud.reduce((n, target) => n + target.endpoint.served.filter((entity) => entity.version).length, 0) : '—'} />
      <Kpi icon="play" label="Opérations en cours" value={count(operations.filter((operation) => ACTIVE.includes(operation.status)).length)} />
      <Kpi icon="warn" label="Opérations en échec" value={count(operations.filter((operation) => operation.status === 'failed').length)} tone="red" />
      <Kpi icon="flag" label="Rollbacks enregistrés" value={count(operations.filter((operation) => operation.kind === 'rollback').length)} hint="Sur l’historique chargé (500 max.)" />
    </div>
    <nav className="dataset-tabs" aria-label="Centre de déploiement">{(['Cibles', 'Historique'] as const).map((name) =>
      <button key={name} className={tab === name ? 'active' : ''} onClick={() => { setTab(name); setOperationId(null); }}>{name}</button>)}</nav>
    {tab === 'Cibles' && <div className={`dataset-layout${selected ? '' : ' dataset-layout-full'}`}>
      <section className="card dataset-list col" style={{ gap: 14 }}><h2 className="h2">Catalogue des cibles</h2>
        <div className="row dataset-filters"><SearchField value={query} onChange={setQuery} placeholder="Rechercher une cible…" />
          <SelectField label="Type de cible" allLabel="Cloud et Edge" value={kind} onChange={setKind} options={[["Cloud", "Cloud"], ["Edge", "Edge"]]} />
          <SelectField label="État" allLabel="Tous les états" value={state} onChange={setState} options={[["ready", "Prêt / en ligne"], ["unready", "À vérifier / hors ligne"]]} /></div>
        {endpoints.loading && <Loading what="Lecture Serving" />}{edge.loading && <Loading what="Lecture Edge" />}
        <span className="muted" style={{ fontSize: 13 }}>{filtered.length} cible(s) dans le périmètre connu</span>
        <div className="dataset-table-wrap"><table className="dataset-table lifecycle-table lifecycle-deployment-table"><thead><tr>
          <th>Cible</th><th>Type</th><th>Modèle</th><th>Version active</th><th>État</th><th className="opt">Compute</th>
          <th className="opt">Dernière vérification</th><th>Opération</th>
        </tr></thead><tbody>{filtered.map((target) => {
          const entity = target.kind === 'Cloud' ? target.endpoint.served[0] : null;
          const edgeModel = target.kind === 'Edge' ? target.station.models.find((item) => item.status === 'loaded') ?? target.station.models[0] : null;
          const active = target.kind === 'Cloud' ? operations.find((operation) => operation.endpoint === target.endpoint.name && ACTIVE.includes(operation.status)) : null;
          return <tr key={target.id} tabIndex={0} className={selectedId === target.id ? 'selected' : ''}
            onClick={() => setSelectedId(target.id)} onKeyDown={(event) => { if (event.key === 'Enter') setSelectedId(target.id); }}>
            <td><b>{target.kind === 'Cloud' ? target.endpoint.name : target.station.name}</b><small>{target.kind === 'Cloud' ? target.model?.uc_name ?? 'Modèle non identifié' : `${target.station.station_id} · ${target.station.cell}`}</small></td>
            <td>{target.kind}</td><td>{target.kind === 'Cloud' ? target.model?.display_name ?? entity?.model ?? '—' : edgeModel?.model?.registered_model ?? 'Aucun modèle chargé'}</td>
            <td>{target.kind === 'Cloud' ? entity?.version ? `v${entity.version}` : '—' : edgeModel?.model?.version ? `v${edgeModel.model.version}` : '—'}</td>
            <td><Chip tone={ready(target) ? 'green' : 'amber'}>{target.kind === 'Cloud' ? target.endpoint.ready === 'READY' ? 'prêt' : 'à vérifier' : target.station.online ? 'en ligne' : 'hors ligne'}</Chip></td>
            <td className="opt">{target.kind === 'Cloud' ? entity?.workload_size ?? '—' : 'Local'}</td>
            <td className="opt">{target.kind === 'Cloud' ? dateTime(endpoints.fetchedAt) : dateTime(target.station.last_seen_at)}</td>
            <td>{active ? <OperationBadge operation={active} /> : '—'}</td>
          </tr>;
        })}</tbody></table></div>
        {!endpoints.loading && !edge.loading && !filtered.length && <Unavailable tone="grey">Aucune cible pour ces critères.</Unavailable>}
      </section>
      {selected && <DeploymentDetail target={selected} operations={operations} statuses={statuses.data ?? []}
        onClose={() => setSelectedId(null)} onOperation={setOperationId} onNew={openWizard}
        onRegistry={(id) => go('registry', id)} />}
    </div>}
    {tab === 'Historique' && <section className="card col" style={{ gap: 12 }}><h2 className="h2">Opérations HOVIS enregistrées</h2>
      {history.loading && <Loading />}{history.data?.length === 0 && <Unavailable tone="grey">Aucun déploiement ni rollback HOVIS enregistré. La présence d’un endpoint ne crée pas d’historique fictif.</Unavailable>}
      {history.data && history.data.length > 0 && <div className="dataset-table-wrap"><table className="dataset-table"><thead><tr>
        <th>Date</th><th>Type</th><th>Cible</th><th>Modèle</th><th>Version</th><th>Statut</th><th>Motif</th><th>Résultat</th>
      </tr></thead><tbody>{history.data.map((operation) => <tr key={operation.operation_id} tabIndex={0}
        onClick={() => setOperationId(operation.operation_id)} onKeyDown={(event) => { if (event.key === 'Enter') setOperationId(operation.operation_id); }}>
        <td>{dateTime(operation.created_at)}</td><td>{operation.kind === 'rollback' ? 'Rollback' : 'Déploiement'}</td>
        <td>{operation.endpoint}</td><td>{operation.model_id}</td><td>v{operation.previous_version} → v{operation.version}</td>
        <td><OperationBadge operation={operation} /></td><td>{operation.reason}</td><td>{operation.verification?.active_version ? `v${operation.verification.active_version}` : '—'}</td>
      </tr>)}</tbody></table></div>}
    </section>}
    {operationId && <OperationPanel key={operationId} id={operationId} initial={selectedOperation} statuses={statuses.data ?? []}
      endpoints={endpoints.data ?? []} onRollback={openRollback} onClose={() => setOperationId(null)} />}
    {wizard && <DeploymentWizard models={models.data ?? []} statuses={statuses.data ?? []} endpoints={endpoints.data ?? []}
      initialEndpoint={selected?.kind === 'Cloud' ? selected.endpoint.name : null}
      rollbackSource={rollbackSource}
      onClose={() => setWizard(false)} onSubmitted={(operation) => { setWizard(false); setOperationId(operation.operation_id); store.invalidate('deployment-history'); }} />}
  </div>;
}
