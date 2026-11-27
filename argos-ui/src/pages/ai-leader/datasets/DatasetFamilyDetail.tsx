import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { mlops, type DatasetFamilySummary, type DatasetVersion } from '../../../api/mlops';
import { Badge, KV, Loading, Panel, Technical, Unavailable } from '../common';
import DatasetDraft from '../DatasetDraft';
import DatasetExplorer, { SPLIT_FR } from '../DatasetExplorer';
import { errText, useDatasetFamily, useFamilyItems, useStore } from '../data';
import { dateTime } from '../metrics';
import { Chip, classColor, Donut, fr, frReview, SelectField, SPLIT_BLUES, StackedBar } from '../ui';

const TABS = ['Vue d’ensemble', 'Versions', 'Splits', 'Annotations', 'Échantillons', 'Lignage'] as const;

export default function DatasetFamilyDetail({ family, onClose }: { family: DatasetFamilySummary; onClose: () => void }) {
  const resource = useDatasetFamily(family.dataset_id);
  const store = useStore();
  const [params, setParams] = useSearchParams();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const index = resource.data;
  const versionParam = params.get('version');
  const version = index?.versions.find((v) => v.version === versionParam) ?? (index?.versions.length ? index.versions[index.versions.length - 1] : null);
  const draftId = params.get('draft');
  const tab = TABS.find((name) => name === params.get('tab')) ?? TABS[0];
  const patch = (values: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) if (value) next.set(key, value); else next.delete(key);
    setParams(next);
  };
  const newDraft = async () => {
    if (!index) return;
    setError(''); setBusy(true);
    try {
      const d = await mlops.createFamilyDraft(family.dataset_id, version?.version ?? null);
      store.invalidate(`family:${family.dataset_id}`, 'dataset-catalog');
      patch({ draft: d.draft_id });
    } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  };

  return <section className="card dataset-detail col" style={{ gap: 14 }}>
    <header className="between dataset-detail-head" style={{ gap: 12 }}>
      <div className="col" style={{ gap: 4 }}><h2 className="h2">{family.name}</h2><span className="muted">{family.dataset_id}</span></div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <Badge tone={family.version_count ? 'green' : 'amber'}>{family.version_count ? `${family.version_count} version(s)` : 'À initialiser'}</Badge>
        <button className="btn btn-ghost" aria-label="Fermer le détail" onClick={onClose}>✕</button>
      </div>
    </header>
    <div className="row dataset-detail-meta"><span>Cas d’usage : <b>{fr(family.use_case)}</b></span><span>Format : <b>{fr(family.annotation_format)}</b></span>
      <span>Dernière publication : <b>{family.last_published_at ? dateTime(family.last_published_at) : 'aucune'}</b></span>
      <span>Modèle(s) lié(s) : <b>{family.linked_models.length ? family.linked_models.join(', ') : 'aucun'}</b></span></div>
    {resource.error && !index && <Unavailable tone="red">{resource.error}</Unavailable>}
    {resource.loading && <Loading what="Lecture de la famille" />}
    {resource.staleError && <Unavailable>Dernière lecture en échec : {resource.staleError}</Unavailable>}
    {error && <Unavailable tone="red">{error}</Unavailable>}
    {index && <>
      <div className="between" style={{ gap: 10, flexWrap: 'wrap' }}>
        {index.versions.length ? <div style={{ minWidth: 220 }}><SelectField label="Version du dataset" icon="none" value={version?.version ?? ''}
          onChange={(v) => patch({ version: v, draft: null })}
          options={[...index.versions].reverse().map((v, i) => [v.version, `Version ${v.version}${i === 0 ? ' · dernière publiée' : ''}`])} /></div>
          : <span className="muted">Aucune version publiée</span>}
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <button className="btn btn-ghost" disabled={!version || !family.linked_models.length}
            title={family.linked_models.length ? 'Ouvrir Training Factory avec cette version sélectionnée' : 'Aucun modèle lié : entraînement indisponible'}
            onClick={() => patch({ section: 'training', model: family.linked_models[0], dataset: version?.version ?? null, version: null, tab: null, draft: null })}>Préparer entraînement</button>
          <button className="btn btn-primary" disabled={busy || !!draftId} onClick={newDraft}>{version ? 'Créer une nouvelle version' : 'Créer la première version'}</button>
        </div>
      </div>
      {index.incomplete.map((entry) => <Unavailable key={entry.version}>
        Publication {entry.state === 'interrupted' ? 'interrompue' : 'en cours'} : {entry.version}.
        {entry.draft_id && <button className="btn btn-ghost" onClick={() => patch({ draft: entry.draft_id })}>Reprendre</button>}
      </Unavailable>)}
      {index.drafts.filter((d) => d.status !== 'published').length > 0 && <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <b>Brouillons :</b>{index.drafts.filter((d) => d.status !== 'published').map((d) =>
          <button key={d.draft_id} className="btn btn-ghost" onClick={() => patch({ draft: d.draft_id })}>
            <Chip tone="amber">Brouillon</Chip> issu de {d.parent_version ?? 'aucune version'} · {d.status === 'open' ? 'ouvert' : 'publication en cours'}</button>)}</div>}
      {draftId ? <DatasetDraft key={draftId} modelId={family.dataset_id} family={family} draftId={draftId} index={index}
        onPublished={(v) => patch({ version: v, draft: null, tab: 'Vue d’ensemble' })} onClose={() => patch({ draft: null })} />
        : <>
          <nav className="dataset-tabs" aria-label="Détail du dataset">{TABS.map((name) => <button key={name} className={tab === name ? 'active' : ''}
            onClick={() => patch({ tab: name })}>{name}</button>)}</nav>
          {tab === 'Vue d’ensemble' && <Overview family={family} version={version} />}
          {tab === 'Versions' && <Versions versions={index.versions} drafts={index.drafts.filter((d) => d.status !== 'published')} selected={version?.version ?? null} onSelect={(v) => patch({ version: v })} onDraft={(d) => patch({ draft: d })} />}
          {tab === 'Splits' && <Splits version={version} />}
          {tab === 'Annotations' && <Annotations key={version?.version ?? 'empty'} family={family} version={version} />}
          {tab === 'Échantillons' && (version ? <DatasetExplorer key={version.version} modelId={family.dataset_id} version={version.version} classes={version.classes} />
            : <Unavailable tone="grey">Publiez une première version pour voir ses échantillons.</Unavailable>)}
          {tab === 'Lignage' && <Lineage family={family} version={version} />}
        </>}
    </>}
  </section>;
}

function classItems(version: DatasetVersion) {
  return version.classes.map((label, i) => ({ label, count: Object.values(version.counts).reduce((n, split) => n + (split[label] ?? 0), 0), color: classColor(label, i) }));
}
function splitItems(version: DatasetVersion) {
  return ['train', 'validation', 'test'].map((k, i) => ({ label: SPLIT_FR[k] ?? k, count: version.ref.splits[k] ?? 0, color: SPLIT_BLUES[i] }));
}

function Overview({ family, version }: { family: DatasetFamilySummary; version: DatasetVersion | null }) {
  if (!version) return <Unavailable tone="grey">Famille créée. Créez un brouillon, importez des images puis publiez sa première version.</Unavailable>;
  const splits = version.ref.splits;
  return <div className="col" style={{ gap: 14 }}>
    <div className="dataset-mini-kpis"><Mini label="Images" value={version.ref.num_samples} /><Mini label="Classes" value={version.classes.length} />
      <Mini label="Train" value={splits.train ?? 0} /><Mini label="Validation" value={splits.validation ?? 0} />
      <Mini label="Test" value={splits.test ?? 0} /><Mini label="Format" value={fr(version.annotation_format)} /></div>
    <div className="dataset-charts"><Panel title="Distribution des classes"><Donut items={classItems(version)} /></Panel>
      <Panel title="Répartition des splits" sub={`Stratégie : ${fr(version.split_strategy)}`}><StackedBar items={splitItems(version)} /></Panel></div>
    <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}><Chip tone={version.locked ? 'green' : 'grey'}>{version.locked ? 'Utilisée par un modèle' : 'Aucun modèle utilisateur connu'}</Chip>
      <span className="muted">{version.used_by.map((u) => `${u.model_id ?? 'modèle'} v${u.model_version}${u.run_id ? ` · run ${u.run_id}` : ''}`).join(' · ')}</span></div>
    <Technical title="Manifeste et origine"><KV k="Volume" v={family.root} /><KV k="SHA-256 du manifeste" v={version.ref.manifest_sha256 ?? '—'} />
      <KV k="Création" v={version.created_at ? dateTime(version.created_at) : '—'} /><KV k="Source" v={JSON.stringify(version.provenance ?? {})} /></Technical>
  </div>;
}

const CHANGE_KEYS: [string, string, 'green' | 'amber' | 'red' | 'blue'][] = [
  ['validated', 'validées', 'green'], ['corrected', 'corrigées', 'amber'], ['excluded', 'exclues', 'red'], ['imported', 'importées', 'blue']];

function Versions({ versions, drafts, selected, onSelect, onDraft }: {
  versions: DatasetVersion[]; drafts: { draft_id: string; parent_version: string | null; status: string; updated_at: string }[];
  selected: string | null; onSelect: (v: string) => void; onDraft: (d: string) => void;
}) {
  const [compare, setCompare] = useState('');
  if (!versions.length && !drafts.length) return <Unavailable tone="grey">Aucune version publiée.</Unavailable>;
  const latest = versions[versions.length - 1] ?? null;
  const current = versions.find((v) => v.version === selected) ?? latest;
  const other = versions.find((v) => v.version === compare) ?? null;
  return <div className="col" style={{ gap: 10 }}>
    {current && versions.length > 1 && <div style={{ maxWidth: 360 }}><SelectField label="Comparer à" icon="none" allLabel={`Comparer ${current.version} à…`} value={compare} onChange={setCompare}
      options={versions.filter((v) => v.version !== current.version).map((v) => [v.version, `Version ${v.version}`])} /></div>}
    {current && other && <div className="dataset-compare"><b>Version {other.version} → version {current.version}</b>
      <span>Images : {other.ref.num_samples} → {current.ref.num_samples} (écart {current.ref.num_samples - other.ref.num_samples})</span>
      <span>Classes : {other.classes.join(', ')} → {current.classes.join(', ')}</span>
      <span>Validation : {other.split_fingerprints.validation === current.split_fingerprints.validation ? 'empreinte identique (évaluations comparables)' : 'empreinte différente (non comparable)'}</span>
      <span>Test : {other.split_fingerprints.test === current.split_fingerprints.test ? 'empreinte identique (évaluations comparables)' : 'empreinte différente (non comparable)'}</span></div>}
    {drafts.map((d) => <button key={d.draft_id} className="dataset-version draft" onClick={() => onDraft(d.draft_id)}>
      <div className="dataset-version-head"><Chip tone="amber">Brouillon</Chip><span>issu de {d.parent_version ?? 'aucune version'}</span></div>
      <span className="muted">{d.status === 'open' ? 'ouvert' : 'publication en cours'} · modifié le {dateTime(d.updated_at)}</span></button>)}
    {[...versions].reverse().map((v) => <button key={v.version} className={`dataset-version${current?.version === v.version ? ' selected' : ''}`} onClick={() => onSelect(v.version)}>
      <div className="dataset-version-head"><b>Version {v.version}</b>
        {current?.version === v.version && <Chip tone="navy">sélectionnée</Chip>}
        {latest?.version === v.version && <Chip tone="blue">dernière publiée</Chip>}
        {!v.parent_version && <Chip tone="grey">version initiale</Chip>}
        <Chip tone={v.used_by.length ? 'green' : 'grey'}>{v.used_by.length ? `utilisée par ${v.used_by.map((u) => `${u.model_id ?? 'modèle'} v${u.model_version}`).join(', ')}` : 'non utilisée'}</Chip>
        {v.evaluation_reference_changed && <Chip tone="amber">référence d’évaluation modifiée</Chip>}</div>
      <span>{v.ref.num_samples} images · {v.classes.length} classes · {v.parent_version ? `issue de ${v.parent_version}` : 'sans parent'} · {v.created_at ? dateTime(v.created_at) : 'date inconnue'}</span>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>{v.changes
        ? CHANGE_KEYS.filter(([k]) => (v.changes?.[k] ?? 0) > 0).map(([k, label, tone]) => <Chip key={k} tone={tone}>{v.changes?.[k]} {label}</Chip>)
        : <span className="muted">Version d’origine : aucune modification enregistrée</span>}
        {v.changes && CHANGE_KEYS.every(([k]) => !(v.changes?.[k])) && <span className="muted">Aucune modification</span>}</div>
      <span className="muted" title={v.ref.manifest_sha256 ?? ''}>Manifeste SHA-256 : {v.ref.manifest_sha256?.slice(0, 12) ?? '—'}…</span>
    </button>)}</div>;
}

function Splits({ version }: { version: DatasetVersion | null }) {
  if (!version) return <Unavailable tone="grey">Aucune version publiée.</Unavailable>;
  const splitKeys = ['train', 'validation', 'test'].filter((k) => k in version.counts);
  return <div className="col" style={{ gap: 12 }}><span className="muted">Stratégie de découpage : {fr(version.split_strategy)}</span>
    <Panel title="Répartition des splits"><StackedBar items={splitItems(version)} /></Panel>
    <Panel title="Classes par split"><div className="dataset-table-wrap"><table className="dataset-table fit"><thead><tr><th>Classe</th>{splitKeys.map((k) => <th key={k}>{SPLIT_FR[k] ?? k}</th>)}<th>Total</th></tr></thead>
      <tbody>{version.classes.map((label, i) => <tr key={label}><td><span className="hv-dot" style={{ display: 'inline-block', marginRight: 6, background: classColor(label, i) }} />{label}</td>
        {splitKeys.map((k) => <td key={k}>{version.counts[k]?.[label] ?? 0}</td>)}
        <td><b>{splitKeys.reduce((n, k) => n + (version.counts[k]?.[label] ?? 0), 0)}</b></td></tr>)}</tbody></table></div></Panel></div>;
}

function Annotations({ family, version }: { family: DatasetFamilySummary; version: DatasetVersion | null }) {
  const [offset, setOffset] = useState(0);
  const [label, setLabel] = useState('');
  const [split, setSplit] = useState('');
  const page = useFamilyItems(family.dataset_id, version?.version ?? null, { offset, limit: 25, label, split });
  if (!version) return <Unavailable tone="grey">Aucune annotation publiée.</Unavailable>;
  return <div className="col" style={{ gap: 10 }}>
    <div className="row dataset-filters"><SelectField label="Filtrer par split" allLabel="Tous les splits" value={split} onChange={(v) => { setSplit(v); setOffset(0); }}
      options={Object.keys(version.ref.splits).map((k) => [k, SPLIT_FR[k] ?? k])} />
      <SelectField label="Filtrer par classe" allLabel="Toutes les classes" value={label} onChange={(v) => { setLabel(v); setOffset(0); }}
        options={version.classes.map((c) => [c, c])} /></div>
    {page.loading && <Loading what="Lecture des annotations" />}{page.error && <Unavailable tone="red">{page.error}</Unavailable>}
    {page.data && <><div className="dataset-table-wrap"><table className="dataset-table"><thead><tr><th>Fichier</th><th>Classe</th><th>Split</th><th>Revue</th><th>Origine</th><th>Historique</th></tr></thead>
      <tbody>{page.data.items.map((item) => <tr key={item.file}><td>{item.file}</td><td>{item.label}</td><td>{SPLIT_FR[item.split] ?? item.split}</td><td>{frReview(item.review)}</td>
        <td>{item.origin ? JSON.stringify(item.origin) : '—'}</td><td>{item.label_history?.map((h) => `${h.version}: ${h.label}`).join(' → ') ?? '—'}</td></tr>)}</tbody></table></div>
      <div className="between"><span className="muted">{page.data.total} annotation(s)</span><div className="row" style={{ gap: 8 }}>
        <button className="btn btn-ghost" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 25))}>Précédent</button>
        <button className="btn btn-ghost" disabled={offset + 25 >= page.data.total} onClick={() => setOffset(offset + 25)}>Suivant</button></div></div></>}
    <span className="muted">Les corrections se font dans un brouillon, puis sont publiées dans une nouvelle version.</span>
  </div>;
}

function Lineage({ family, version }: { family: DatasetFamilySummary; version: DatasetVersion | null }) {
  return <div className="col" style={{ gap: 10 }}><Panel title="Origine"><KV k="Famille" v={family.dataset_id} /><KV k="Volume" v={family.root} />
    <KV k="Cas d’usage" v={fr(family.use_case)} /><KV k="Nature déclarée" v={family.synthetic ? 'synthétique' : 'non synthétique'} /></Panel>
    {version && <Panel title="Version sélectionnée"><KV k="Version" v={version.version} /><KV k="Version parent" v={version.parent_version ?? 'aucune'} />
      <KV k="Manifeste parent" v={version.parent_manifest_sha256 ?? '—'} /><KV k="Utilisée par" v={version.used_by.length ? JSON.stringify(version.used_by) : 'aucune version de modèle référencée'} />
      <KV k="Empreintes des splits" v={JSON.stringify(version.split_fingerprints)} /></Panel>}
    {family.linked_models.length === 0 && <Unavailable tone="grey">Aucun modèle n’est associé à cette famille. La préparation d’entraînement sera disponible après raccordement explicite d’un modèle.</Unavailable>}
  </div>;
}

function Mini({ label, value }: { label: string; value: string | number }) { return <div className="dataset-mini"><span className="muted">{label}</span><b>{value}</b></div>; }
