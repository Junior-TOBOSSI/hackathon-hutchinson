import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { mlops, type DatasetFamilySummary } from '../../api/mlops';
import { Badge, Loading, Stat, Unavailable } from './common';
import { errText, useDatasetCatalog, useHealth, useStore } from './data';
import DatasetFamilyDetail from './datasets/DatasetFamilyDetail';
import './datasets/catalog.css';

const useCases = ['quality', 'workstation', 'safety'] as const;
const useCaseName: Record<string, string> = { quality: 'Qualité', workstation: 'Poste', safety: 'Safety' };

export default function Datasets() {
  const catalog = useDatasetCatalog();
  const health = useHealth();
  const store = useStore();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('');
  const [format, setFormat] = useState('');
  const [sort, setSort] = useState<'name' | 'date' | 'size'>('name');
  const [page, setPage] = useState(0);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const selected = params.get('dataset');
  const families = catalog.data ?? [];
  const filtered = useMemo(() => families
    .filter((f) => (!filter || f.use_case === filter) && (!format || f.annotation_format === format))
    .filter((f) => `${f.name} ${f.dataset_id} ${f.use_case} ${f.classes.join(' ')}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
    .sort((a, b) => sort === 'size' ? (b.latest_images ?? 0) - (a.latest_images ?? 0)
      : sort === 'date' ? (b.last_published_at ?? '').localeCompare(a.last_published_at ?? '')
        : a.name.localeCompare(b.name)), [families, filter, query, sort]);
  const visible = filtered.slice(page * 10, page * 10 + 10);
  const select = (id: string | null) => {
    const next = new URLSearchParams(params);
    for (const key of ['dataset', 'version', 'tab', 'draft']) next.delete(key);
    if (id) next.set('dataset', id);
    setParams(next);
  };
  const current = families.find((f) => f.dataset_id === selected) ?? null;
  const imageCount = families.some((f) => f.version_count && f.latest_images == null)
    ? null : families.reduce((sum, f) => sum + (f.latest_images ?? 0), 0);
  const versionCount = families.reduce((sum, f) => sum + f.version_count, 0);
  const totalDrafts = families.reduce((sum, f) => sum + f.draft_count, 0);

  return <div className="dataset-catalog col" style={{ gap: 14 }}>
    <header className="card dataset-hero">
      <div><h1 className="h2">Datasets — Catalogue & versions</h1>
        <p className="muted">Gérez vos données d’entraînement, leurs annotations, leurs versions et leur traçabilité.</p>
        <span className="muted" style={{ fontSize: 13 }}>Dernière synchronisation : {catalog.fetchedAt ? new Date(catalog.fetchedAt).toLocaleString('fr-FR') : 'indisponible'} · {catalog.cache === 'stale' ? 'dernière valeur connue' : catalog.cache === 'hit' ? 'cache serveur' : 'lecture directe'}</span></div>
      <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
        <button className="btn btn-ghost" onClick={() => store.invalidate('dataset-catalog')}>Actualiser</button>
        <Badge tone={health.error ? 'red' : health.data?.ok ? 'green' : 'amber'}>{health.error ? 'Databricks indisponible' : health.data?.ok ? 'Databricks connecté' : 'Connexion en cours'}</Badge>
      </div>
    </header>
    {catalog.error && !catalog.data && <Unavailable tone="red">Catalogue indisponible : {catalog.error}</Unavailable>}
    {catalog.staleError && <Unavailable>Dernière actualisation en échec : {catalog.staleError}</Unavailable>}
    {error && <Unavailable tone="red">{error}</Unavailable>}
    {catalog.loading && <Loading what="Lecture du catalogue" />}
    {catalog.data && <>
      <div className="dataset-kpis">
        <Stat label="Datasets enregistrés" value={families.length} />
        <Stat label="Versions publiées" value={versionCount} />
        <Stat label="Images" value={imageCount == null ? 'Indisponible' : imageCount.toLocaleString('fr-FR')} hint="Somme des dernières versions" />
        <Stat label="Datasets liés aux modèles" value={families.filter((f) => f.linked_models.length > 0).length} />
        <Stat label="Brouillons actifs" value={totalDrafts} tone={totalDrafts ? 'amber' : undefined} />
        <Stat label="Dernière publication" value={latestDate(families)} />
      </div>
      <div className={`dataset-layout${current ? '' : ' dataset-layout-full'}`}>
        <section className="card dataset-list col" style={{ gap: 14 }}>
          <div className="between" style={{ gap: 10, flexWrap: 'wrap' }}>
            <h2 className="h2">Catalogue des datasets</h2>
            <button className="btn btn-primary" onClick={() => setCreating((value) => !value)}>＋ Ajouter un dataset</button>
          </div>
          {creating && <CreateFamily onCreated={(id) => { setCreating(false); store.invalidate('dataset-catalog'); select(id); }} onError={setError} />}
          <div className="row dataset-filters">
            <input className="input" placeholder="Rechercher un dataset…" value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} />
            <select className="input" aria-label="Cas d'usage" value={filter} onChange={(event) => { setFilter(event.target.value); setPage(0); }}>
              <option value="">Tous les cas d’usage</option>{useCases.map((c) => <option key={c} value={c}>{useCaseName[c]}</option>)}
            </select>
            <select className="input" aria-label="Format d'annotation" value={format} onChange={(event) => { setFormat(event.target.value); setPage(0); }}>
              <option value="">Tous les formats</option>{Array.from(new Set(families.map((f) => f.annotation_format))).map((f) => <option key={f}>{f}</option>)}
            </select>
            <select className="input" aria-label="Trier" value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}>
              <option value="name">Nom</option><option value="date">Publication récente</option><option value="size">Nombre d’images</option>
            </select>
          </div>
          <span className="muted" style={{ fontSize: 13 }}>{filtered.length} résultat(s)</span>
          <div className="dataset-table-wrap"><table className="dataset-table"><thead><tr>
            <th>Dataset</th><th>Cas d’usage</th><th>Dernière version</th><th>Versions</th><th>Images</th><th>Splits</th><th>Modèles liés</th><th>Publication</th><th>Action</th>
          </tr></thead><tbody>{visible.map((f) => <tr key={f.dataset_id} className={selected === f.dataset_id ? 'selected' : ''}
            onClick={() => select(f.dataset_id)} tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter') select(f.dataset_id); }}>
            <td><b>{f.name}</b><small>{f.dataset_id}</small></td>
            <td>{useCaseName[f.use_case] ?? f.use_case}</td><td>{f.latest_version ?? '—'}</td><td>{f.version_count}</td><td>{f.latest_images ?? '—'}</td>
            <td>{f.latest_splits ? Object.entries(f.latest_splits).map(([k, v]) => `${k}: ${v}`).join(' / ') : '—'}</td>
            <td>{f.linked_models.length ? f.linked_models.join(', ') : '—'}</td><td>{f.last_published_at ? new Date(f.last_published_at).toLocaleDateString('fr-FR') : '—'}</td><td><button className="btn btn-ghost" onClick={() => select(f.dataset_id)}>Ouvrir</button></td>
          </tr>)}</tbody></table></div>
          {!filtered.length && <Unavailable tone="grey">Aucun dataset pour ces critères.</Unavailable>}
          {filtered.length > 10 && <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
            <button className="btn btn-ghost" disabled={!page} onClick={() => setPage(page - 1)}>Précédent</button>
            <span>{page + 1} / {Math.ceil(filtered.length / 10)}</span>
            <button className="btn btn-ghost" disabled={page + 1 >= Math.ceil(filtered.length / 10)} onClick={() => setPage(page + 1)}>Suivant</button>
          </div>}
        </section>
        {current && <DatasetFamilyDetail key={current.dataset_id} family={current} onClose={() => select(null)} />}
      </div>
    </>}
  </div>;
}

function latestDate(families: DatasetFamilySummary[]) {
  const dates = families.map((f) => f.last_published_at).filter((date): date is string => !!date);
  return dates.length ? new Date(dates.sort()[dates.length - 1]).toLocaleDateString('fr-FR') : '—';
}

function CreateFamily({ onCreated, onError }: { onCreated: (id: string) => void; onError: (message: string) => void }) {
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [useCase, setUseCase] = useState<'quality' | 'workstation' | 'safety'>('workstation');
  const [classes, setClasses] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); onError('');
    try {
      await mlops.createDatasetFamily({ dataset_id: id.trim(), name: name.trim(), use_case: useCase,
        classes: classes.split(',').map((c) => c.trim()).filter(Boolean), synthetic: true, description: description.trim() || null });
      onCreated(id.trim());
    } catch (e) { onError(errText(e)); } finally { setBusy(false); }
  };
  return <form className="dataset-create" onSubmit={submit}>
    <b>Nouvelle famille indépendante</b><span className="muted">Crée la famille seule ; aucun modèle ni version ne sont créés.</span>
    <div className="dataset-form-grid">
      <label>Identifiant<input className="input" required pattern="[A-Za-z0-9][A-Za-z0-9_-]*" value={id} onChange={(e) => setId(e.target.value)} placeholder="presse-5s" /></label>
      <label>Nom<input className="input" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Presse 5S" /></label>
      <label>Cas d’usage<select className="input" value={useCase} onChange={(e) => setUseCase(e.target.value as typeof useCase)}>{useCases.map((c) => <option key={c} value={c}>{useCaseName[c]}</option>)}</select></label>
      <label>Classes, séparées par des virgules<input className="input" required value={classes} onChange={(e) => setClasses(e.target.value)} placeholder="good, disorder, zone_object, zone_person" /></label>
      <label>Description<input className="input" value={description} onChange={(e) => setDescription(e.target.value)} /></label>
    </div>
    <button className="btn btn-primary" disabled={busy}>{busy ? 'Création…' : 'Créer la famille'}</button>
  </form>;
}
