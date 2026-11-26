import { useState } from 'react';
import { datasetImageUrl, mlops, type DatasetItem, type Draft, type DraftChange } from '../../api/mlops';
import { Badge, KV, Loading, Panel, Technical, Unavailable } from './common';
import { errText, useDatasetItems, useStore } from './data';

/* Explorateur d'une version publiée : 24 images par page, chargées à la demande
   (loading="lazy"), servies par le backend depuis la liste blanche du manifeste.
   En mode brouillon, les modifications en attente sont superposées (jamais écrites
   dans la version publiée). */

const PAGE = 24;
export const SPLIT_FR: Record<string, string> = { train: 'entraînement', validation: 'validation', test: 'test' };
const REVIEW_FR: Record<string, string> = { none: 'non revue', validated: 'validée', corrected: 'corrigée', imported: 'importée' };
const ACTION_FR: Record<string, string> = { validate: 'à valider', relabel: 'à corriger', exclude: 'à exclure' };
export const isEvaluation = (split: string) => split === 'validation' || split === 'test';

export default function DatasetExplorer({ modelId, version, classes, draft }: { modelId: string; version: string; classes: string[]; draft?: Draft | null }) {
  const store = useStore();
  const [filters, setFilters] = useState({ split: '', label: '', review: '', q: '' });
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<DatasetItem | null>(null);
  const [error, setError] = useState('');
  const page = useDatasetItems(modelId, version, { ...filters, offset, limit: PAGE });
  const editable = draft?.status === 'open';

  const setFilter = (k: keyof typeof filters, v: string) => { setFilters({ ...filters, [k]: v }); setOffset(0); };
  const apply = async (change: DraftChange) => {
    if (!draft) return;
    setError('');
    try {
      await mlops.updateDraftItems(modelId, draft.draft_id, [change]);
      store.invalidate(`draft:${modelId}:${draft.draft_id}`, `datasets:${modelId}`);
    } catch (e) {
      setError(errText(e));
    }
  };

  const data = page.data;
  const facets = data?.facets;
  return (
    <Panel title={draft ? `Images de ${version} · brouillon` : `Images de ${version}`}
      sub={draft ? 'Les modifications sont enregistrées dans le brouillon ; la version publiée reste inchangée.' : 'Version publiée : consultation seule'}
      right={data ? <span className="muted" style={{ fontSize: 14 }}>{data.total} élément(s){page.refreshing ? ' · actualisation…' : ''}</span> : undefined}>
      <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
        <Select label="Split" value={filters.split} onChange={(v) => setFilter('split', v)} options={Object.keys(facets?.split ?? {}).map((s) => [s, `${SPLIT_FR[s] ?? s} (${facets?.split[s]})`])} />
        <Select label="Classe" value={filters.label} onChange={(v) => setFilter('label', v)} options={Object.keys(facets?.label ?? {}).map((s) => [s, `${s} (${facets?.label[s]})`])} />
        <Select label="Revue" value={filters.review} onChange={(v) => setFilter('review', v)} options={Object.keys(facets?.review ?? {}).map((s) => [s, `${REVIEW_FR[s] ?? s} (${facets?.review[s]})`])} />
        <input className="input" placeholder="Nom de fichier…" value={filters.q} maxLength={100} onChange={(e) => setFilter('q', e.target.value)} style={{ height: 38, padding: '0 12px', borderRadius: 10, border: '1px solid var(--line-strong)', minWidth: 180 }} />
      </div>
      {error && <Unavailable tone="red">{error}</Unavailable>}
      {page.loading && <Loading what="Chargement des annotations" />}
      {page.error && <Unavailable tone="red">Annotations indisponibles : {page.error}</Unavailable>}
      {data && data.total === 0 && <Unavailable tone="grey">Aucun élément ne correspond aux filtres.</Unavailable>}
      {data && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(118px, 1fr))', gap: 10 }}>
          {data.items.map((item) => {
            const change = draft?.changes[item.file];
            const active = selected?.file === item.file;
            return (
              <button key={item.file} onClick={() => setSelected(active ? null : item)} title={item.file}
                style={{ padding: 6, borderRadius: 12, cursor: 'pointer', textAlign: 'left', background: active ? 'var(--surface-soft)' : '#fff', border: `2px solid ${change ? 'var(--amber)' : active ? 'var(--primary)' : 'var(--line)'}`, opacity: change?.action === 'exclude' ? 0.45 : 1 }}>
                <img src={datasetImageUrl(modelId, version, item.file)} alt={item.file} loading="lazy" decoding="async" width={104} height={104}
                  style={{ width: '100%', height: 'auto', aspectRatio: '1 / 1', objectFit: 'contain', imageRendering: 'pixelated', borderRadius: 8, background: 'var(--track)' }} />
                <div className="row" style={{ gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
                  <Badge tone={item.label === 'NOK' ? 'red' : 'green'}>{change?.action === 'relabel' ? `${item.label}→${change.label}` : item.label}</Badge>
                  <Badge tone={isEvaluation(item.split) ? 'blue' : 'grey'}>{SPLIT_FR[item.split] ?? item.split}</Badge>
                </div>
                {change && <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--amber-text)' }}>{ACTION_FR[change.action] ?? change.action}</span>}
              </button>
            );
          })}
        </div>
      )}
      {data && data.total > PAGE && (
        <div className="row" style={{ gap: 10, alignItems: 'center' }}>
          <button className="btn btn-ghost" style={{ height: 36 }} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Précédent</button>
          <span className="muted" style={{ fontSize: 14 }}>{offset + 1}–{Math.min(offset + PAGE, data.total)} sur {data.total}</span>
          <button className="btn btn-ghost" style={{ height: 36 }} disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Suivant →</button>
        </div>
      )}
      {selected && <ItemDetail modelId={modelId} version={version} item={selected} classes={classes} draft={editable ? draft : null} onApply={apply} />}
    </Panel>
  );
}

function ItemDetail({ modelId, version, item, classes, draft, onApply }: { modelId: string; version: string; item: DatasetItem; classes: string[]; draft: Draft | null | undefined; onApply: (c: DraftChange) => void }) {
  const change = draft?.changes[item.file];
  const others = classes.filter((c) => c !== item.label);
  const known = new Set(['file', 'label', 'split', 'sha256', 'review', 'previous_label', 'origin', 'label_history']);
  const metadata = Object.entries(item).filter(([k]) => !known.has(k));
  const evaluation = isEvaluation(item.split);
  return (
    <div className="row" style={{ gap: 18, alignItems: 'flex-start', flexWrap: 'wrap', padding: 14, borderRadius: 14, background: 'var(--surface-soft)' }}>
      <img src={datasetImageUrl(modelId, version, item.file)} alt={item.file} width={192} height={192} style={{ imageRendering: 'pixelated', borderRadius: 10, background: 'var(--track)' }} />
      <div className="col" style={{ gap: 8, flex: 1, minWidth: 260 }}>
        <b style={{ overflowWrap: 'anywhere' }}>{item.file}</b>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          <Badge tone={item.label === 'NOK' ? 'red' : 'green'}>classe {item.label}</Badge>
          <Badge tone={evaluation ? 'blue' : 'grey'}>{SPLIT_FR[item.split] ?? item.split}</Badge>
          <Badge tone="grey">{REVIEW_FR[item.review ?? 'none'] ?? item.review}</Badge>
          {item.previous_label && <Badge tone="amber">corrigée (avant : {item.previous_label})</Badge>}
        </div>
        {metadata.length > 0 && (
          <div style={{ fontSize: 13 }}>
            {metadata.map(([k, v]) => <KV key={k} k={k} v={v === null ? '—' : typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(3)) : String(v)} />)}
          </div>
        )}
        {item.label_history && item.label_history.length > 1 && (
          <span className="muted" style={{ fontSize: 13 }}>Historique : {item.label_history.map((h) => `${h.version} ${h.label}${h.review ? ` (${REVIEW_FR[h.review] ?? h.review})` : ''}`).join(' → ')}</span>
        )}
        {draft && (
          <div className="col" style={{ gap: 8 }}>
            {evaluation && <Unavailable>Élément du jeu de {SPLIT_FR[item.split]} : le modifier change la référence d'évaluation (signalé dans le manifeste ; les évaluations ne seront plus comparables).</Unavailable>}
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              <button className="btn btn-ghost" style={{ height: 36 }} onClick={() => onApply({ file: item.file, action: 'validate' })}>Valider l'annotation</button>
              {others.map((c) => <button key={c} className="btn btn-ghost" style={{ height: 36 }} onClick={() => onApply({ file: item.file, action: 'relabel', label: c })}>Corriger en {c}</button>)}
              <button className="btn btn-ghost" style={{ height: 36 }} onClick={() => onApply({ file: item.file, action: 'exclude' })}>Exclure de la nouvelle version</button>
              {change && <button className="btn btn-ghost" style={{ height: 36 }} onClick={() => onApply({ file: item.file, action: 'reset' })}>Annuler la modification</button>}
            </div>
            {change && <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--amber-text)' }}>En attente dans le brouillon : {ACTION_FR[change.action] ?? change.action}{change.label ? ` (${change.label})` : ''}</span>}
          </div>
        )}
        <Technical title="Empreinte et provenance">
          <KV k="SHA-256" v={item.sha256} />
          {item.origin && <KV k="origine" v={JSON.stringify(item.origin)} />}
        </Technical>
      </div>
    </div>
  );
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <label className="row" style={{ gap: 6, alignItems: 'center', fontSize: 14 }}>
      <span className="muted" style={{ fontWeight: 600 }}>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} style={{ height: 38, borderRadius: 10, border: '1px solid var(--line-strong)', padding: '0 8px', background: '#fff' }}>
        <option value="">Tous</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}
