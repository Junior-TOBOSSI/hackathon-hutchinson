import { useMemo, useState } from 'react';
import { useManaged, useStatuses, useStore } from './data';
import { useNav, Loading, Unavailable } from './common';
import { fr, Kpi, SearchField, SelectField } from './ui';
import { dateTime } from './metrics';
import { decisionOf, modelCatalog, modelCounts } from './lifecycleCatalog';
import RegistryDetail from './RegistryDetail';
import './datasets/catalog.css';
import './lifecycle.css';

export { MetricsBlock } from './RegistryDetail'; // Training Factory keeps its existing import.

export default function Registry({ onMessage }: { onMessage: (message: string) => void }) {
  const { model: selectedId, go } = useNav();
  const managed = useManaged();
  const statuses = useStatuses();
  const store = useStore();
  const [query, setQuery] = useState('');
  const [useCase, setUseCase] = useState('');
  const [decision, setDecision] = useState('');
  const [sort, setSort] = useState('name');
  const [page, setPage] = useState(0);
  const rows = useMemo(() => modelCatalog(managed.data ?? [], statuses.data ?? []), [managed.data, statuses.data]);
  const counts = modelCounts(rows);
  const filtered = useMemo(() => rows.filter((row) =>
    (!useCase || row.model.argos_use_case === useCase)
    && (!decision || (decision === 'pending' ? row.pending > 0
      : decision === 'approved' ? !!row.status?.versions.some((v) => decisionOf(v) === 'approved') : row.versions === 0))
    && `${row.model.display_name} ${row.model.id} ${row.model.uc_name} ${row.architecture ?? ''} ${row.task ?? ''}`
      .toLocaleLowerCase('fr').includes(query.toLocaleLowerCase('fr')))
    .sort((a, b) => sort === 'activity' ? (b.activity ?? '').localeCompare(a.activity ?? '')
      : sort === 'versions' ? b.versions - a.versions : a.model.display_name.localeCompare(b.model.display_name, 'fr')),
  [rows, useCase, decision, query, sort]);
  const selected = rows.find((row) => row.model.id === selectedId) ?? null;
  const visible = filtered.slice(page * 10, page * 10 + 10);
  const change = (setter: (value: string) => void) => (value: string) => { setter(value); setPage(0); };
  const value = (n: number) => statuses.data ? n : '—';

  return <div className="dataset-catalog lifecycle-catalog col" style={{ gap: 14 }}>
    <header className="card dataset-hero"><div><h1 className="h2">Registre des modèles — Catalogue & versions</h1>
      <p className="muted">Familles de modèles gérées par ARGOS · versions Unity Catalog et décisions humaines.</p>
      <span className="muted lifecycle-fresh">Périmètre : {managed.data?.length ?? '—'} modèle(s) configuré(s) · lecture UC : {dateTime(statuses.fetchedAt)}{statuses.cache === 'stale' ? ' · dernière valeur connue' : ''}</span></div>
      <button className="btn btn-ghost" disabled={managed.refreshing || statuses.refreshing} onClick={() => store.invalidate('models', 'statuses')}>Actualiser</button></header>
    {managed.error && <Unavailable tone="red">Catalogue indisponible : {managed.error}</Unavailable>}
    {statuses.error && <Unavailable tone="red">Versions UC indisponibles : {statuses.error}</Unavailable>}
    {statuses.staleError && <Unavailable>Dernière lecture UC en échec : {statuses.staleError}</Unavailable>}
    <div className="dataset-kpis">
      <Kpi icon="db" label="Modèles enregistrés" value={value(counts.models)} hint="Périmètre ARGOS" />
      <Kpi icon="layers" label="Versions enregistrées" value={value(counts.versions)} />
      <Kpi icon="warn" label="En attente de décision" value={value(counts.pending)} tone={counts.pending ? 'amber' : undefined} />
      <Kpi icon="check" label="Versions approuvées" value={value(counts.approved)} tone="green" />
      <Kpi icon="flag" label="Champions" value={value(counts.champions)} hint="Alias UC" />
      <Kpi icon="monitor" label="Versions servies" value={value(counts.served)} hint="Serving effectif" />
    </div>
    <div className={`dataset-layout${selected ? '' : ' dataset-layout-full'}`}>
      <section className="card dataset-list col" style={{ gap: 14 }}>
        <div className="between" style={{ gap: 10, flexWrap: 'wrap' }}><h2 className="h2">Catalogue des modèles</h2><span className="muted">{filtered.length} résultat(s)</span></div>
        <div className="row dataset-filters">
          <SearchField value={query} onChange={change(setQuery)} placeholder="Rechercher un modèle…" />
          <SelectField label="Cas d’usage" allLabel="Tous les cas d’usage" value={useCase} onChange={change(setUseCase)}
            options={[...new Set(rows.map((row) => row.model.argos_use_case))].map((item) => [item, fr(item)])} />
          <SelectField label="Décision" allLabel="Toutes les décisions" value={decision} onChange={change(setDecision)}
            options={[["pending", "Candidats en attente"], ["approved", "Avec approbation"], ["empty", "Sans version"]]} />
          <SelectField label="Trier" icon="sort" value={sort} onChange={change(setSort)}
            options={[["name", "Nom"], ["activity", "Activité récente"], ["versions", "Nombre de versions"]]} />
        </div>
        {managed.loading && <Loading what="Lecture des modèles gérés" />}
        {statuses.loading && <Loading what="Lecture des versions UC" />}
        <div className="dataset-table-wrap"><table className="dataset-table lifecycle-table lifecycle-registry-table"><thead><tr>
          <th>Modèle</th><th>Cas d’usage</th><th className="opt">Tâche / architecture</th><th>Versions</th><th>Dernière</th>
          <th>Champion</th><th>Servie</th><th>En attente</th><th className="opt">Activité</th><th>Action</th>
        </tr></thead><tbody>{visible.map((row) => <tr key={row.model.id} tabIndex={0} className={selectedId === row.model.id ? 'selected' : ''}
          onClick={() => go('registry', row.model.id)} onKeyDown={(event) => { if (event.key === 'Enter') go('registry', row.model.id); }}>
          <td><b>{row.model.display_name}</b><small>{row.model.uc_name}</small></td>
          <td>{fr(row.model.argos_use_case)}</td><td className="opt">{[row.task, row.architecture].filter(Boolean).join(' / ') || 'Non renseignées'}</td>
          <td>{statuses.data ? row.versions : '—'}</td><td>{row.latest ? `v${row.latest.version.version}` : '—'}</td>
          <td>{row.champion ? `v${row.champion}` : '—'}</td><td>{row.served ? `v${row.served}` : '—'}</td>
          <td>{statuses.data ? row.pending : '—'}</td><td className="opt">{dateTime(row.activity)}</td>
          <td><button className="btn btn-ghost" onClick={(event) => { event.stopPropagation(); go('registry', row.model.id); }}>Ouvrir</button></td>
        </tr>)}</tbody></table></div>
        {!managed.loading && !visible.length && <Unavailable tone="grey">Aucun modèle pour ces critères.</Unavailable>}
        {filtered.length > 10 && <div className="row lifecycle-pagination">
          <button className="btn btn-ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>Précédent</button>
          <span>{page + 1} / {Math.ceil(filtered.length / 10)}</span>
          <button className="btn btn-ghost" disabled={page + 1 >= Math.ceil(filtered.length / 10)} onClick={() => setPage(page + 1)}>Suivant</button>
        </div>}
      </section>
      {selected && <RegistryDetail key={selected.model.id} row={selected} onClose={() => go('registry', null)} onMessage={onMessage} />}
    </div>
  </div>;
}
