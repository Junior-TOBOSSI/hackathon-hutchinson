import { useMemo, useState } from 'react';
import type { ManagedModel, ModelStatus } from '../../api/mlops';
import { Loading, Unavailable } from './common';
import { useEdgeModelStatus, useEdgeStation, useEdgeStations } from './lifecycleData';
import { filterStations, modelState, modelText, rawModelText, stationModel, USE_CASES } from './fleetSelectors';
import { dateTime } from './metrics';
import { Chip, fr, Kpi, SearchField, SelectField } from './ui';
import FleetWizard from './FleetWizard';

const PAGE_SIZE = 20;
const tone = (state: string): 'green' | 'red' | 'amber' | 'grey' => state === 'Erreur' ? 'red'
  : state === 'Chargement' || state === 'Dernière version connue' ? 'amber'
    : state.startsWith('Chargé') ? 'green' : 'grey';

export default function IndustrialFleet({ models, statuses }: { models: ManagedModel[]; statuses: ModelStatus[] }) {
  const stations = useEdgeStations();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [checked, setChecked] = useState<string[]>([]);
  const [wizard, setWizard] = useState(false);
  const [query, setQuery] = useState('');
  const [cell, setCell] = useState('');
  const [model, setModel] = useState('');
  const [useCase, setUseCase] = useState('');
  const [connection, setConnection] = useState('');
  const [version, setVersion] = useState('');
  const [sort, setSort] = useState('station');
  const [page, setPage] = useState(0);
  const all = stations.data ?? [];
  const filtered = useMemo(() => filterStations(all, { query, cell, model, useCase, connection, version, sort }),
    [all, query, cell, model, useCase, connection, version, sort]);
  const visible = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const selected = all.find((station) => station.station_id === selectedId) ?? null;
  const detail = useEdgeStation(selectedId);
  const raw = useEdgeModelStatus(selectedId);
  const change = (setter: (value: string) => void) => (value: string) => { setter(value); setPage(0); };
  const toggle = (id: string) => setChecked((current) => current.includes(id)
    ? current.filter((item) => item !== id) : [...current, id]);
  const pageIds = visible.map((station) => station.station_id);
  const allChecked = pageIds.length > 0 && pageIds.every((id) => checked.includes(id));
  const togglePage = () => setChecked((current) => allChecked
    ? current.filter((id) => !pageIds.includes(id)) : [...new Set([...current, ...pageIds])]);
  const known = stations.data !== null;
  const realLoaded = all.filter((station) => station.online && !station.simulated)
    .reduce((count, station) => count + station.models.filter((item) => item.status === 'loaded').length, 0);
  const modelNames = [...new Set(all.flatMap((station) => station.models.map((item) => item.model?.registered_model).filter((name): name is string => !!name)))].sort();
  const versions = [...new Set(all.flatMap((station) => station.models.map((item) => item.model?.version).filter((v): v is string => !!v)))].sort();

  return <div className="col" style={{ gap: 14 }}>
    <div className="dataset-kpis">
      <Kpi icon="monitor" label="Machines recensées" value={known ? all.length : 'Indisponible'} hint={known ? `${all.filter((s) => s.simulated).length} simulée(s) signalée(s)` : 'Lecture Core nécessaire'} />
      <Kpi icon="check" label="Machines connectées" value={known ? all.filter((s) => s.online).length : 'Indisponible'} hint="Présence estimée par le Core" tone="green" />
      <Kpi icon="layers" label="Modèles effectivement chargés" value={known ? realLoaded : 'Indisponible'} hint="Statuts Edge de postes réels en ligne" />
      <Kpi icon="warn" label="Écarts de version" value="Indisponible" hint="Version souhaitée non exposée" tone="amber" />
      <Kpi icon="play" label="Déploiements Edge en cours" value="Indisponible" hint="Suivi Edge non implémenté" />
      <Kpi icon="flag" label="Machines hors ligne" value={known ? all.filter((s) => !s.online).length : 'Indisponible'} hint="Selon la dernière communication" tone="red" />
    </div>
    {stations.error && <Unavailable tone="red">Parc industriel indisponible : {stations.error}</Unavailable>}
    {stations.staleError && <Unavailable>Dernière lecture Core en échec : {stations.staleError}. Dernière liste connue affichée.</Unavailable>}
    <section className="card dataset-list col" style={{ gap: 14 }}>
      <div className="between" style={{ gap: 10, flexWrap: 'wrap' }}><div><h2 className="h2">Parc industriel</h2>
        <span className="muted">Source : Core · dernière lecture {dateTime(stations.fetchedAt)} · modèles simulés identifiés</span></div>
        <button className="btn btn-primary" disabled={!checked.length} onClick={() => setWizard(true)}>Déployer sur la sélection ({checked.length})</button></div>
      <div className="row dataset-filters">
        <SearchField value={query} onChange={change(setQuery)} placeholder="Rechercher un poste…" />
        <SelectField label="Cellule" allLabel="Toutes les cellules" value={cell} onChange={change(setCell)} options={[...new Set(all.map((s) => s.cell))].sort().map((s) => [s, s])} />
        <SelectField label="Modèle" allLabel="Tous les modèles signalés" value={model} onChange={change(setModel)} options={modelNames.map((s) => [s, s])} />
        <SelectField label="Cas d’usage" allLabel="Tous les cas d’usage" value={useCase} onChange={change(setUseCase)} options={USE_CASES.map((s) => [s, fr(s)])} />
        <SelectField label="Connexion" allLabel="Tous les états" value={connection} onChange={change(setConnection)} options={[["online", "Connectées"], ["offline", "Hors ligne"]]} />
        <SelectField label="Version chargée" allLabel="Toutes les versions" value={version} onChange={change(setVersion)} options={versions.map((s) => [s, `v${s}`])} />
        <label className="hv-field hv-select" title="Version souhaitée non exposée par le Core"><select className="hv-input" aria-label="Écarts de déploiement" disabled><option>Écarts : indisponible</option></select></label>
        <SelectField label="Tri" icon="sort" value={sort} onChange={change(setSort)} options={[["station", "Identifiant"], ["cell", "Cellule"], ["connection", "Connexion"], ["lastSeen", "Communication récente"]]} />
      </div>
      {stations.loading && <Loading what="Lecture du parc Core" />}
      <span className="muted" style={{ fontSize: 13 }}>{known ? `${filtered.length} poste(s) · ${checked.length} sélectionné(s)` : 'Nombre de postes indisponible'}</span>
      <div className="dataset-table-wrap"><table className="dataset-table lifecycle-table lifecycle-fleet-table"><thead><tr>
        <th><input type="checkbox" aria-label="Sélectionner la page" checked={allChecked} onChange={togglePage} disabled={!pageIds.length} /></th>
        <th>Poste</th><th>Cellule</th><th>Connexion</th><th>Quality</th><th>Safety</th><th>Workstation / 5S</th><th>Dernière communication</th><th>Action</th>
      </tr></thead><tbody>{visible.map((station) => <tr key={station.station_id}>
        <td><input type="checkbox" aria-label={`Sélectionner ${station.station_id}`} checked={checked.includes(station.station_id)} onChange={() => toggle(station.station_id)} /></td>
        <td><b>{station.station_id}</b>{station.simulated && <small>Simulation</small>}</td><td>{station.cell || 'Indisponible'}</td>
        <td><Chip tone={station.online ? 'green' : 'amber'}>{station.online ? 'Connectée' : 'Hors ligne'}</Chip></td>
        {USE_CASES.map((useCase) => <td key={useCase}><b>{modelText(station, useCase)}</b>
          <small><Chip tone={tone(modelState(station, useCase))}>{modelState(station, useCase)}</Chip></small></td>)}
        <td>{dateTime(station.last_seen_at)}</td><td><button className="btn btn-ghost" onClick={() => setSelectedId(station.station_id)}>Détail</button></td>
      </tr>)}</tbody></table></div>
      {known && !filtered.length && <Unavailable tone="grey">Aucune machine pour ces critères. Le Core de cette recette peut avoir une base vide ; aucun poste fictif n’est ajouté.</Unavailable>}
      {filtered.length > PAGE_SIZE && <div className="row lifecycle-pagination"><button className="btn btn-ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>Précédent</button>
        <span>{page + 1} / {Math.ceil(filtered.length / PAGE_SIZE)}</span><button className="btn btn-ghost" disabled={(page + 1) * PAGE_SIZE >= filtered.length} onClick={() => setPage(page + 1)}>Suivant</button></div>}
    </section>
    {selected && <div className="lifecycle-overlay" onClick={() => setSelectedId(null)}><section className="card lifecycle-fleet-drawer col" onClick={(event) => event.stopPropagation()} style={{ gap: 14 }}>
      <header className="between"><div><h2 className="h2">Poste {selected.station_id}</h2><span className="muted">{selected.simulated ? 'Poste de démonstration · modèles non industriels' : 'Poste industriel'}</span></div>
        <button className="btn btn-ghost" aria-label="Fermer" onClick={() => setSelectedId(null)}>✕</button></header>
      {detail.loading && <Loading what="Configuration du poste" />}{detail.error && <Unavailable tone="red">{detail.error}</Unavailable>}
      <div className="dataset-mini-kpis"><Fact label="Connexion" value={(detail.data ?? selected).online ? 'Connectée' : 'Hors ligne'} />
        <Fact label="Cellule" value={(detail.data ?? selected).cell || 'Indisponible'} />
        <Fact label="Dernière communication" value={dateTime((detail.data ?? selected).last_seen_at)} />
        <Fact label="Configuration désirée" value="Indisponible" /></div>
      <h3>Modèles signalés par model.status</h3>
      {raw.loading && <Loading what="Statuts des modèles" />}{raw.error && <Unavailable tone="red">Statuts indisponibles : {raw.error}</Unavailable>}
      {raw.data?.length === 0 && <Unavailable tone="grey">Aucun événement model.status reçu pour ce poste.</Unavailable>}
      {raw.data?.map((item) => { const projection = stationModel(detail.data ?? selected, item.use_case); return <div className="lifecycle-event" key={item.use_case}>
        <div className="between" style={{ width: '100%' }}><b>{fr(item.use_case)}</b><Chip tone={item.loaded ? 'green' : 'red'}>{item.loaded ? 'Chargé' : 'Erreur'}</Chip></div>
        <span>{rawModelText(item)}{selected.simulated ? ' · simulé' : ''}</span>
        <small>Version souhaitée : Indisponible · Date de chargement : {dateTime(projection?.loaded_at ?? null)}</small>
        <small>Empreinte package : {item.package_sha256 ?? 'Indisponible'}</small>{item.error && <small>Erreur : {item.error}</small>}
      </div>; })}
      <Unavailable tone="grey">Le Core ne publie ni version souhaitée, ni compatibilité de package, ni commande de distribution Edge. L’état « à jour » ne peut pas être établi.</Unavailable>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}><button className="btn btn-primary" disabled title="Backend Edge requis">Déployer une version</button>
        <button className="btn btn-ghost" disabled title="Backend Edge requis">Redéployer la même version</button>
        <button className="btn btn-ghost" disabled title="Backend Edge requis">Rollback</button></div>
    </section></div>}
    {wizard && <FleetWizard stations={all.filter((station) => checked.includes(station.station_id))} models={models.filter((item) => !item.synthetic)}
      statuses={statuses} onClose={() => setWizard(false)} />}
  </div>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="dataset-mini"><span className="muted">{label}</span><b>{value}</b></div>;
}
