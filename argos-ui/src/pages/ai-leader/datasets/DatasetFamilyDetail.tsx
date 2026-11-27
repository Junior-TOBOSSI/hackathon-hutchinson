import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { mlops, type DatasetFamilySummary, type DatasetVersion } from '../../../api/mlops';
import { Badge, KV, Loading, Panel, Technical, Unavailable } from '../common';
import DatasetDraft from '../DatasetDraft';
import DatasetExplorer, { SPLIT_FR } from '../DatasetExplorer';
import { errText, useDatasetFamily, useFamilyItems, useStore } from '../data';
import { dateTime } from '../metrics';

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
    <div className="row dataset-detail-meta"><span>Cas d’usage : <b>{family.use_case}</b></span><span>Format : <b>{family.annotation_format}</b></span>
      <span>Dernière publication : <b>{family.last_published_at ? dateTime(family.last_published_at) : 'aucune'}</b></span>
      <span>Modèle(s) lié(s) : <b>{family.linked_models.length ? family.linked_models.join(', ') : 'aucun'}</b></span></div>
    {resource.error && !index && <Unavailable tone="red">{resource.error}</Unavailable>}
    {resource.loading && <Loading what="Lecture de la famille" />}
    {resource.staleError && <Unavailable>Dernière lecture en échec : {resource.staleError}</Unavailable>}
    {error && <Unavailable tone="red">{error}</Unavailable>}
    {index && <>
      <div className="between" style={{ gap: 10, flexWrap: 'wrap' }}>
        <label className="row" style={{ gap: 8 }}>Version
          <select className="input" aria-label="Version du dataset" value={version?.version ?? ''} disabled={!version}
            onChange={(event) => patch({ version: event.target.value, draft: null })}>
            {index.versions.length === 0 && <option value="">Aucune version</option>}
            {index.versions.map((v) => <option key={v.version} value={v.version}>{v.version}</option>)}
          </select></label>
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
          <button key={d.draft_id} className="btn btn-ghost" onClick={() => patch({ draft: d.draft_id })}>{d.draft_id} · {d.status}</button>)}</div>}
      {draftId ? <DatasetDraft key={draftId} modelId={family.dataset_id} family={family} draftId={draftId} index={index}
        onPublished={(v) => patch({ version: v, draft: null, tab: 'Vue d’ensemble' })} onClose={() => patch({ draft: null })} />
        : <>
          <nav className="dataset-tabs" aria-label="Détail du dataset">{TABS.map((name) => <button key={name} className={tab === name ? 'active' : ''}
            onClick={() => patch({ tab: name })}>{name}</button>)}</nav>
          {tab === 'Vue d’ensemble' && <Overview family={family} version={version} />}
          {tab === 'Versions' && <Versions versions={index.versions} selected={version?.version ?? null} onSelect={(v) => patch({ version: v })} />}
          {tab === 'Splits' && <Splits version={version} />}
          {tab === 'Annotations' && <Annotations key={version?.version ?? 'empty'} family={family} version={version} />}
          {tab === 'Échantillons' && (version ? <DatasetExplorer key={version.version} modelId={family.dataset_id} version={version.version} classes={version.classes} />
            : <Unavailable tone="grey">Publiez une première version pour voir ses échantillons.</Unavailable>)}
          {tab === 'Lignage' && <Lineage family={family} version={version} />}
        </>}
    </>}
  </section>;
}

function Overview({ family, version }: { family: DatasetFamilySummary; version: DatasetVersion | null }) {
  if (!version) return <Unavailable tone="grey">Famille créée. Créez un brouillon, importez des images puis publiez sa première version.</Unavailable>;
  const splits = version.ref.splits;
  const total = version.ref.num_samples;
  const labels = version.classes.map((label) => ({ label, count: Object.values(version.counts).reduce((n, split) => n + (split[label] ?? 0), 0) }));
  return <div className="col" style={{ gap: 14 }}>
    <div className="dataset-mini-kpis"><Mini label="Images" value={total} /><Mini label="Classes" value={version.classes.length} />
      <Mini label="Train" value={splits.train ?? 0} /><Mini label="Validation" value={splits.validation ?? 0} />
      <Mini label="Test" value={splits.test ?? 0} /><Mini label="Format" value={version.annotation_format} /></div>
    <div className="dataset-charts"><Panel title="Répartition des splits"><Bars items={Object.entries(splits).map(([label, count]) => ({ label: SPLIT_FR[label] ?? label, count }))} /></Panel>
      <Panel title="Distribution des classes"><Bars items={labels} /></Panel></div>
    <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}><Badge tone={version.locked ? 'green' : 'grey'}>{version.locked ? 'Utilisée par un modèle' : 'Aucun modèle utilisateur connu'}</Badge>
      <span className="muted">{version.used_by.map((u) => `${u.model_id ?? 'modèle'} v${u.model_version}${u.run_id ? ` · run ${u.run_id}` : ''}`).join(' · ')}</span></div>
    <Technical title="Manifeste et origine"><KV k="Volume" v={family.root} /><KV k="SHA-256 du manifeste" v={version.ref.manifest_sha256 ?? '—'} />
      <KV k="Création" v={version.created_at ? dateTime(version.created_at) : '—'} /><KV k="Source" v={JSON.stringify(version.provenance ?? {})} /></Technical>
  </div>;
}

function Versions({ versions, selected, onSelect }: { versions: DatasetVersion[]; selected: string | null; onSelect: (v: string) => void }) {
  const [compare, setCompare] = useState('');
  if (!versions.length) return <Unavailable tone="grey">Aucune version publiée.</Unavailable>;
  const current = versions.find((v) => v.version === selected) ?? versions[versions.length - 1];
  const other = versions.find((v) => v.version === compare) ?? null;
  return <div className="col" style={{ gap: 8 }}><label className="row" style={{ gap: 8 }}>Comparer à
    <select className="input" value={compare} onChange={(event) => setCompare(event.target.value)}><option value="">Choisir une version</option>
      {versions.filter((v) => v.version !== current.version).map((v) => <option key={v.version}>{v.version}</option>)}</select></label>
    {other && <div className="dataset-compare"><b>{other.version} → {current.version}</b>
      <span>Images : {other.ref.num_samples} → {current.ref.num_samples} (écart {current.ref.num_samples - other.ref.num_samples})</span>
      <span>Classes : {other.classes.join(', ')} → {current.classes.join(', ')}</span>
      <span>Validation : {other.split_fingerprints.validation === current.split_fingerprints.validation ? 'empreinte identique' : 'empreinte différente'}</span>
      <span>Test : {other.split_fingerprints.test === current.split_fingerprints.test ? 'empreinte identique' : 'empreinte différente'}</span></div>}
    {[...versions].reverse().map((v) => <button key={v.version} className="dataset-version" onClick={() => onSelect(v.version)}
    style={{ borderColor: selected === v.version ? 'var(--primary)' : undefined }}>
    <b>{v.version}</b><span>{v.ref.num_samples} images · {v.classes.length} classes</span>
    <span>{v.parent_version ? `Issue de ${v.parent_version}` : 'Version initiale'}</span>
    <span>{v.created_at ? dateTime(v.created_at) : 'Date inconnue'}</span>
    <span>{v.changes ? Object.entries(v.changes).map(([key, n]) => `${key}: ${n}`).join(' · ') : 'Modifications inconnues'}</span>
    <span>{v.used_by.length ? v.used_by.map((u) => `${u.model_id ?? 'modèle'} v${u.model_version}`).join(', ') : 'Aucun modèle'}</span>
    <span title={v.ref.manifest_sha256 ?? ''}>SHA-256 : {v.ref.manifest_sha256?.slice(0, 12) ?? '—'}…</span>
    {v.evaluation_reference_changed && <Badge tone="amber">Référence d’évaluation modifiée</Badge>}
  </button>)}</div>;
}

function Splits({ version }: { version: DatasetVersion | null }) {
  if (!version) return <Unavailable tone="grey">Aucune version publiée.</Unavailable>;
  return <div className="col" style={{ gap: 10 }}><span className="muted">Stratégie de découpage : {version.split_strategy}</span><div className="dataset-charts"><Panel title="Répartition des splits"><Bars items={Object.entries(version.ref.splits).map(([label, count]) => ({ label: SPLIT_FR[label] ?? label, count }))} /></Panel>
    <Panel title="Classes par split"><table className="dataset-table"><thead><tr><th>Classe</th>{Object.keys(version.counts).map((s) => <th key={s}>{SPLIT_FR[s] ?? s}</th>)}</tr></thead>
      <tbody>{version.classes.map((label) => <tr key={label}><td>{label}</td>{Object.values(version.counts).map((split, i) => <td key={i}>{split[label] ?? 0}</td>)}</tr>)}</tbody></table></Panel></div></div>;
}

function Annotations({ family, version }: { family: DatasetFamilySummary; version: DatasetVersion | null }) {
  const [offset, setOffset] = useState(0);
  const [label, setLabel] = useState('');
  const [split, setSplit] = useState('');
  const page = useFamilyItems(family.dataset_id, version?.version ?? null, { offset, limit: 25, label, split });
  if (!version) return <Unavailable tone="grey">Aucune annotation publiée.</Unavailable>;
  return <div className="col" style={{ gap: 10 }}>
    <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}><select className="input" aria-label="Filtrer par split" value={split} onChange={(e) => { setSplit(e.target.value); setOffset(0); }}>
      <option value="">Tous les splits</option>{Object.keys(version.ref.splits).map((s) => <option key={s} value={s}>{SPLIT_FR[s] ?? s}</option>)}</select>
      <select className="input" aria-label="Filtrer par classe" value={label} onChange={(e) => { setLabel(e.target.value); setOffset(0); }}>
        <option value="">Toutes les classes</option>{version.classes.map((c) => <option key={c}>{c}</option>)}</select></div>
    {page.loading && <Loading what="Lecture des annotations" />}{page.error && <Unavailable tone="red">{page.error}</Unavailable>}
    {page.data && <><div className="dataset-table-wrap"><table className="dataset-table"><thead><tr><th>Fichier</th><th>Classe</th><th>Split</th><th>Revue</th><th>Origine</th><th>Historique</th></tr></thead>
      <tbody>{page.data.items.map((item) => <tr key={item.file}><td>{item.file}</td><td>{item.label}</td><td>{SPLIT_FR[item.split] ?? item.split}</td><td>{item.review ?? '—'}</td>
        <td>{item.origin ? JSON.stringify(item.origin) : '—'}</td><td>{item.label_history?.map((h) => `${h.version}: ${h.label}`).join(' → ') ?? '—'}</td></tr>)}</tbody></table></div>
      <div className="between"><span className="muted">{page.data.total} annotation(s)</span><div className="row" style={{ gap: 8 }}>
        <button className="btn btn-ghost" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 25))}>Précédent</button>
        <button className="btn btn-ghost" disabled={offset + 25 >= page.data.total} onClick={() => setOffset(offset + 25)}>Suivant</button></div></div></>}
    <span className="muted">Les corrections se font dans un brouillon, puis sont publiées dans une nouvelle version.</span>
  </div>;
}

function Lineage({ family, version }: { family: DatasetFamilySummary; version: DatasetVersion | null }) {
  return <div className="col" style={{ gap: 10 }}><Panel title="Origine"><KV k="Famille" v={family.dataset_id} /><KV k="Volume" v={family.root} />
    <KV k="Cas d’usage" v={family.use_case} /><KV k="Nature déclarée" v={family.synthetic ? 'synthétique' : 'non synthétique'} /></Panel>
    {version && <Panel title="Version sélectionnée"><KV k="Version" v={version.version} /><KV k="Version parent" v={version.parent_version ?? 'aucune'} />
      <KV k="Manifeste parent" v={version.parent_manifest_sha256 ?? '—'} /><KV k="Utilisée par" v={version.used_by.length ? JSON.stringify(version.used_by) : 'aucune version de modèle référencée'} />
      <KV k="Empreintes des splits" v={JSON.stringify(version.split_fingerprints)} /></Panel>}
    {family.linked_models.length === 0 && <Unavailable tone="grey">Aucun modèle n’est associé à cette famille. La préparation d’entraînement sera disponible après raccordement explicite d’un modèle.</Unavailable>}
  </div>;
}

function Mini({ label, value }: { label: string; value: string | number }) { return <div className="dataset-mini"><span className="muted">{label}</span><b>{value}</b></div>; }
function Bars({ items }: { items: { label: string; count: number }[] }) {
  const total = items.reduce((n, item) => n + item.count, 0);
  return <div className="col" style={{ gap: 12 }}>{items.map((item) => <div key={item.label} className="col" style={{ gap: 4 }}>
    <div className="between"><span>{item.label}</span><b>{item.count.toLocaleString('fr-FR')} ({total ? Math.round(item.count * 100 / total) : 0} %)</b></div>
    <div className="dataset-bar"><span style={{ width: `${total ? item.count * 100 / total : 0}%` }} /></div>
  </div>)}{!items.length && <span className="muted">Aucune donnée.</span>}</div>;
}
