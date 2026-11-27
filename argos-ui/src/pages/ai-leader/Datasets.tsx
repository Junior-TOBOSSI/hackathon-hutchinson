import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { mlops, type DatasetFamilySummary } from '../../api/mlops';
import { Icon, ICONS } from '../../components/ui';
import { Badge, Loading, Unavailable } from './common';
import { errText, useDatasetCatalog, useHealth, useStore } from './data';
import DatasetFamilyDetail from './datasets/DatasetFamilyDetail';
import './datasets/catalog.css';
import { usePipelines } from './training/shared';
import { fr, Kpi, SearchField, SelectField } from './ui';

const useCases = ['quality', 'workstation', 'safety'] as const;
const SPLIT_SHORT: Record<string, string> = { train: 'train', validation: 'val', test: 'test' };
const useCaseName: Record<string, string> = { quality: fr('quality'), workstation: fr('workstation'), safety: fr('safety') };

export default function Datasets() {
  const catalog = useDatasetCatalog();
  const pipelines = usePipelines();
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
  // Expected = declared by a training pipeline but not published yet (no hardcoded list).
  const expected = (pipelines.data ?? []).flatMap((v) => v.spec.dataset.families.map((id) => ({
    id, name: id, useCase: v.spec.use_case, status: `déclaré par le pipeline « ${v.spec.name} » — aucune version publiée`,
  }))).filter((item, i, all) => all.findIndex((x) => x.id === item.id) === i)
    .filter((item) => !families.some((family) => family.dataset_id === item.id))
    .filter((item) => (!filter || item.useCase === filter) && (!query || `${item.name} ${item.id}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())));

  return <div className="dataset-catalog col" style={{ gap: 14 }}>
    <header className="card dataset-hero">
      <div><h1 className="h2">Datasets — Catalogue & versions</h1>
        <p className="muted">Gérez vos données d’entraînement, leurs annotations, leurs versions et leur traçabilité.</p></div>
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
        <Kpi icon="db" label="Datasets enregistrés" value={families.length} />
        <Kpi icon="layers" label="Versions publiées" value={versionCount} />
        <Kpi icon="camera" label="Images" value={imageCount == null ? 'Indisponible' : imageCount.toLocaleString('fr-FR')} hint="Somme des dernières versions" />
        <Kpi icon="grid" label="Datasets liés aux modèles" value={families.filter((f) => f.linked_models.length > 0).length} />
        <Kpi icon="log" label="Brouillons actifs" value={totalDrafts} tone={totalDrafts ? 'amber' : undefined} />
        <Kpi icon="check" label="Dernière publication" value={latestDate(families)} />
      </div>
      <div className={`dataset-layout${current ? '' : ' dataset-layout-full'}`}>
        <section className="card dataset-list col" style={{ gap: 14 }}>
          <div className="between" style={{ gap: 10, flexWrap: 'wrap' }}>
            <h2 className="h2">Catalogue des datasets</h2>
            <button className="btn btn-primary" onClick={() => setCreating((value) => !value)}>＋ Ajouter un dataset</button>
          </div>
          {creating && <CreateFamily onCreated={(id) => { setCreating(false); store.invalidate('dataset-catalog'); select(id); }} onError={setError} />}
          <div className="row dataset-filters">
            <SearchField placeholder="Rechercher un dataset…" value={query} onChange={(v) => { setQuery(v); setPage(0); }} />
            <SelectField label="Cas d’usage" allLabel="Tous les cas d’usage" value={filter} onChange={(v) => { setFilter(v); setPage(0); }}
              options={useCases.map((c) => [c, useCaseName[c]])} />
            <SelectField label="Format d’annotation" allLabel="Tous les formats" value={format} onChange={(v) => { setFormat(v); setPage(0); }}
              options={Array.from(new Set(families.map((f) => f.annotation_format))).map((f) => [f, fr(f)])} />
            <SelectField label="Trier" icon="sort" value={sort} onChange={(v) => setSort(v as typeof sort)}
              options={[['name', 'Trier par nom'], ['date', 'Publication récente'], ['size', 'Nombre d’images']]} />
          </div>
          <span className="muted" style={{ fontSize: 13 }}>{filtered.length} résultat(s)</span>
          <div className="dataset-table-wrap"><table className="dataset-table"><thead><tr>
            <th>Dataset</th><th>Cas d’usage</th><th>Dernière version</th><th className="opt">Versions</th><th>Images</th><th className="opt">Splits</th><th className="opt">Modèles liés</th><th className="opt">Publication</th><th className="opt">Action</th>
          </tr></thead><tbody>{visible.map((f) => <tr key={f.dataset_id} className={selected === f.dataset_id ? 'selected' : ''}
            onClick={() => select(f.dataset_id)} tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter') select(f.dataset_id); }}>
            <td><b>{f.name}</b><small>{f.dataset_id}</small></td>
            <td>{useCaseName[f.use_case] ?? fr(f.use_case)}</td><td>{f.latest_version ?? '—'}</td><td className="opt">{f.version_count}</td><td>{f.latest_images ?? '—'}</td>
            <td className="opt">{f.latest_splits ? Object.entries(f.latest_splits).map(([k, v]) => `${SPLIT_SHORT[k] ?? k} ${v}`).join(' / ') : '—'}</td>
            <td className="opt">{f.linked_models.length ? f.linked_models.join(', ') : '—'}</td><td className="opt">{f.last_published_at ? new Date(f.last_published_at).toLocaleDateString('fr-FR') : '—'}</td><td className="opt"><button className="btn btn-ghost" onClick={() => select(f.dataset_id)}>Ouvrir</button></td>
          </tr>)}</tbody></table></div>
          {!filtered.length && <Unavailable tone="grey">Aucun dataset pour ces critères.</Unavailable>}
          {expected.length > 0 && <div className="card col" style={{ gap: 8, padding: 14 }}><b>Jeux scientifiques attendus — non publiés</b>
            <span className="muted">Ces entrées ne sont pas des versions Databricks et ne comptent pas dans les indicateurs du catalogue.</span>
            {expected.map((item) => <span key={item.id}><b>{item.name}</b> · {item.id} — {item.status}</span>)}
          </div>}
          {filtered.length > 10 && <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
            <button className="btn btn-ghost" disabled={!page} onClick={() => setPage(page - 1)}>Précédent</button>
            <span>{page + 1} / {Math.ceil(filtered.length / 10)}</span>
            <button className="btn btn-ghost" disabled={page + 1 >= Math.ceil(filtered.length / 10)} onClick={() => setPage(page + 1)}>Suivant</button>
          </div>}
        </section>
        {current && <DatasetFamilyDetail key={current.dataset_id} family={current} onClose={() => select(null)} />}
      </div>
      <Lifecycle />
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

/* Lifecycle of a dataset version, as implemented by the catalogue: a draft (import, annotation,
   checks) is published through the integrity checks into an immutable, versioned version. */
const EDIT = 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4 M14 3v5h5 M19 8v2 M14.5 21l1-3.5 5.5-5.5a1.4 1.4 0 0 1 2 2L17.5 20z';
const STEPS = [
  { tone: 'amber', icon: EDIT, title: 'Brouillon', text: 'Importation, annotation et vérification' },
  { tone: 'blue', icon: ICONS.db, title: 'Enregistrement', text: 'Contrôles d’intégrité et versionnement' },
  { tone: 'green', icon: 'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18z M8 12l3 3 5-6', title: 'Disponible', text: 'Version figée, utilisable pour l’entraînement' },
] as const;

function Lifecycle() {
  return <section className="card dataset-lifecycle">
    <h2 className="h2" style={{ fontSize: 20 }}>Cycle de vie d’une version</h2>
    <ol className="dataset-lifecycle-steps">{STEPS.map((step, i) => <li key={step.title} className="row">
      {i > 0 && <span className="dataset-lifecycle-arrow" aria-hidden>→</span>}
      <div className={`dataset-step ${step.tone}`}>
        <Icon d={step.icon} size={24} /><b>{step.title}</b><span>{step.text}</span>
      </div>
    </li>)}</ol>
  </section>;
}
