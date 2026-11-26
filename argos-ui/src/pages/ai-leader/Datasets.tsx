import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { mlops, type DatasetIndex, type DatasetVersion } from '../../api/mlops';
import { Badge, grid, KV, LinkButton, Loading, Panel, Technical, Unavailable } from './common';
import DatasetDraft from './DatasetDraft';
import DatasetExplorer, { SPLIT_FR } from './DatasetExplorer';
import { errText, useDatasets, useDatasetTables, useStore, useTrainingDataset } from './data';
import { dateTime } from './metrics';
import { useSelection } from './selection';

/* Datasets (DBX-04) : versions lues dans les manifestes du Volume Unity Catalog
   (source de vérité), via la Files API — jamais de SQL warehouse. Rien n'est chargé
   avant l'ouverture de la section ; les images sont paginées et chargées à la demande. */

const SPLITS = ['train', 'validation', 'test'];

/** ?dataset=<version> et ?draft=<id> en plus de ?section et ?model. */
function useDatasetParams() {
  const [params, setParams] = useSearchParams();
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) if (v) next.set(k, v); else next.delete(k);
    setParams(next);
  };
  return { dataset: params.get('dataset'), draft: params.get('draft'), set, params, setParams };
}

export default function Datasets() {
  const { model, loading, error } = useSelection();
  const index = useDatasets(model?.id ?? null);
  const { dataset, draft, set } = useDatasetParams();
  const [resume, setResume] = useState<string | null>(null);

  if (error) return <Unavailable tone="red">{error}</Unavailable>;
  if (loading || !model) return <Loading />;
  if (index.error && !index.data) return <Unavailable tone="red">Datasets indisponibles : {index.error}</Unavailable>;
  if (!index.data) return <Panel title={`Données de ${model.display_name}`}><Loading what="Lecture des manifestes du Volume" /></Panel>;

  const idx = index.data;
  const selected = idx.versions.find((v) => v.version === dataset) ?? idx.versions[idx.versions.length - 1] ?? null;
  return (
    <>
      <Header modelId={model.id} name={model.display_name} synthetic={model.synthetic} index={idx} staleError={index.staleError} />
      {idx.incomplete.map((p) => (
        <Unavailable key={p.version}>
          {p.state === 'publishing' ? `Publication de « ${p.version} » en cours.` : `Publication interrompue : « ${p.version} » n'a pas de manifeste, ce n'est donc pas une version.`}
          {p.draft_id && p.state === 'interrupted' && <> <LinkButton onClick={() => { setResume(p.version); set({ draft: p.draft_id }); }}>Reprendre depuis le brouillon</LinkButton></>}
        </Unavailable>
      ))}
      <VersionList index={idx} selected={selected?.version ?? null} onSelect={(v) => set({ dataset: v, draft: null })} onDraft={(id) => set({ draft: id })} />
      {draft
        ? <DatasetDraft key={draft} modelId={model.id} draftId={draft} index={idx} resumeVersion={resume}
            onPublished={(v) => set({ dataset: v, draft: null })} onClose={() => set({ draft: null })} />
        : selected && (
          <>
            <VersionDetail modelId={model.id} v={selected} index={idx} onDraft={(id) => set({ draft: id })} />
            <DatasetExplorer key={selected.version} modelId={model.id} version={selected.version} classes={selected.classes} />
          </>
        )}
      {idx.versions.length === 0 && <Unavailable tone="grey">Aucune version publiée dans {idx.root}.</Unavailable>}
      <TablesPanel modelId={model.id} />
    </>
  );
}

function Header({ modelId, name, synthetic, index, staleError }: { modelId: string; name: string; synthetic: boolean; index: DatasetIndex; staleError: string | null }) {
  const training = useTrainingDataset(modelId);
  return (
    <Panel title={`Données de ${name}`} sub="Versions lues dans les manifestes du Volume Unity Catalog (source de vérité)"
      right={synthetic ? <Badge tone="amber">Données synthétiques</Badge> : undefined}>
      <div className="row" style={{ gap: 18, flexWrap: 'wrap', fontSize: 14 }}>
        <span><b>{index.versions.length}</b> version(s) publiée(s)</span>
        <span><b>{index.drafts.filter((d) => d.status === 'open').length}</b> brouillon(s) ouvert(s)</span>
        <span>
          Job d'entraînement : {training.loading ? '…' : training.data?.dataset_version
            ? <>configuré sur <b>{training.data.dataset_version}</b> <span className="muted">(lu dans sa définition)</span></>
            : <span className="muted">{training.error ?? 'dataset non déterminé'}</span>}
        </span>
      </div>
      {staleError && <Unavailable>Dernière lecture en échec ({staleError}) : informations du dernier résultat connu.</Unavailable>}
      <Technical title="Emplacement"><KV k="Volume" v={index.root} /><KV k="nom du dataset" v={index.name ?? '—'} /></Technical>
    </Panel>
  );
}

function VersionList({ index, selected, onSelect, onDraft }: { index: DatasetIndex; selected: string | null; onSelect: (v: string) => void; onDraft: (id: string) => void }) {
  const drafts = index.drafts.filter((d) => d.status !== 'published');
  return (
    <div style={grid(260)}>
      {[...index.versions].reverse().map((v) => {
        const active = v.version === selected;
        const total = Object.values(v.ref.splits).reduce((a, b) => a + b, 0);
        return (
          <button key={v.version} className="card col" onClick={() => onSelect(v.version)}
            style={{ gap: 6, textAlign: 'left', cursor: 'pointer', border: `2px solid ${active ? 'var(--primary)' : 'transparent'}`, minWidth: 0 }}>
            <div className="between" style={{ flexWrap: 'wrap', gap: 6 }}><span className="h2" style={{ fontSize: 20 }}>{v.version}</span>{v.locked ? <Badge tone="blue">utilisée par {v.used_by.map((u) => `v${u.model_version}`).join(', ')}</Badge> : <Badge tone="grey">non utilisée</Badge>}</div>
            <span className="muted" style={{ fontSize: 13 }}>{total} images · {v.classes.join(' / ')} · {v.parent_version ? `issue de ${v.parent_version}` : 'version initiale'}</span>
            <span className="muted" style={{ fontSize: 13 }}>{v.created_at ? `créée le ${dateTime(v.created_at)}` : 'date de création non renseignée'}</span>
            {v.evaluation_reference_changed && <Badge tone="amber">référence d'évaluation modifiée</Badge>}
          </button>
        );
      })}
      {drafts.map((d) => (
        <button key={d.draft_id} className="card col" onClick={() => onDraft(d.draft_id)} style={{ gap: 6, textAlign: 'left', cursor: 'pointer', border: '2px dashed var(--line-strong)', minWidth: 0 }}>
          <div className="between" style={{ flexWrap: 'wrap', gap: 6 }}><b>Brouillon</b><Badge tone={d.status === 'open' ? 'blue' : 'amber'}>{d.status === 'open' ? 'ouvert' : `publication : ${d.target_version}`}</Badge></div>
          <span className="muted" style={{ fontSize: 13 }}>à partir de {d.parent_version} · {d.n_changes} modification(s) · {d.n_imports} import(s)</span>
          <span className="muted" style={{ fontSize: 13 }}>modifié le {dateTime(d.updated_at)}</span>
        </button>
      ))}
    </div>
  );
}

function VersionDetail({ modelId, v, index, onDraft }: { modelId: string; v: DatasetVersion; index: DatasetIndex; onDraft: (id: string) => void }) {
  const store = useStore();
  const { setParams, params } = useDatasetParams();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const parent = index.versions.find((p) => p.version === v.parent_version) ?? null;
  const total = Object.values(v.ref.splits).reduce((a, b) => a + b, 0);

  const newDraft = async () => {
    setBusy(true); setError('');
    try {
      const d = await mlops.createDraft(modelId, v.version);
      store.invalidate(`datasets:${modelId}`);
      onDraft(d.draft_id);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  };
  const toTraining = () => {
    const next = new URLSearchParams({ section: 'training', dataset: v.version });
    const m = params.get('model');
    if (m) next.set('model', m);
    setParams(next);
    window.scrollTo({ top: 0 });
  };

  return (
    <Panel title={`Version ${v.version}`} sub={`${v.use_case ?? '—'} · ${v.annotation_format === 'classification' ? 'classification' : `format d'annotation : ${v.annotation_format}`} · ${total} images`}
      right={<div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <button className="btn btn-ghost" style={{ height: 38 }} disabled={busy} onClick={newDraft}>Nouveau brouillon à partir de cette version</button>
        <button className="btn btn-ghost" style={{ height: 38 }} onClick={toTraining}>Retrouver dans Training Factory</button>
      </div>}>
      {error && <Unavailable tone="red">{error}</Unavailable>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 18, alignItems: 'start' }}>
        <div className="col" style={{ gap: 8 }}>
          <b>Effectifs par split et par classe</b>
          <table style={{ borderCollapse: 'collapse', fontSize: 14 }}>
            <thead><tr><th style={th}>Split</th>{v.classes.map((c) => <th key={c} style={th}>{c}</th>)}<th style={th}>Total</th></tr></thead>
            <tbody>{SPLITS.map((s) => (
              <tr key={s}><td style={td}>{SPLIT_FR[s]}</td>{v.classes.map((c) => <td key={c} style={td}>{v.counts[s]?.[c] ?? 0}</td>)}<td style={td}><b>{v.ref.splits[s] ?? 0}</b></td></tr>
            ))}</tbody>
          </table>
          <span className="muted" style={{ fontSize: 13 }}>Stratégie de séparation : {v.split_strategy}</span>
        </div>
        <div className="col" style={{ gap: 8, fontSize: 14 }}>
          <b>Provenance et utilisation</b>
          <span>{v.parent_version ? <>Issue de <b>{v.parent_version}</b></> : 'Version initiale'} · {v.synthetic ? 'données synthétiques' : 'données réelles'}{v.created_by ? ` · créée par ${v.created_by === 'ai_leader' ? "l'AI Leader" : v.created_by}` : ''}</span>
          <span>{v.used_by.length ? <>Entraînement des versions de modèle {v.used_by.map((u) => `v${u.model_version}`).join(', ')} <span className="muted">(empreinte du manifeste identique au tag MLflow)</span></> : "Aucune version de modèle n'a été entraînée sur ce dataset."}</span>
          {v.changes && <span>Modifications : {v.changes.validated} validée(s), {v.changes.corrected} corrigée(s), {v.changes.excluded} exclue(s), {v.changes.imported} importée(s)</span>}
          {parent && <Comparability v={v} parent={parent} />}
          {v.description && <span className="muted">{v.description}</span>}
        </div>
      </div>
      <Technical title="Empreintes, DatasetRef et provenance">
        <KV k="SHA-256 du manifeste" v={v.ref.manifest_sha256 ?? '—'} />
        {v.parent_manifest_sha256 && <KV k="SHA-256 du manifeste parent" v={v.parent_manifest_sha256} />}
        {Object.entries(v.split_fingerprints).map(([s, f]) => <KV key={s} k={`empreinte ${SPLIT_FR[s] ?? s}`} v={f} />)}
        <KV k="URI" v={v.uri} />
        {Object.entries(v.provenance).map(([k, val]) => <KV key={k} k={k} v={typeof val === 'object' ? JSON.stringify(val) : String(val)} />)}
        <KV k="DatasetRef" v={JSON.stringify(v.ref)} />
        {v.excluded_items.length > 0 && <KV k="éléments exclus" v={v.excluded_items.map((e) => e.file).join(', ')} />}
      </Technical>
    </Panel>
  );
}

/** Two evaluations are comparable on a split only if its fingerprint is identical. */
function Comparability({ v, parent }: { v: DatasetVersion; parent: DatasetVersion }) {
  const same = (s: string) => v.split_fingerprints[s] === parent.split_fingerprints[s];
  return (
    <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
      {['validation', 'test'].map((s) => (
        <Badge key={s} tone={same(s) ? 'green' : 'amber'}>{SPLIT_FR[s]} {same(s) ? `identique à ${parent.version}` : `différent de ${parent.version} (non comparable)`}</Badge>
      ))}
    </div>
  );
}

function TablesPanel({ modelId }: { modelId: string }) {
  const tables = useDatasetTables(modelId);
  return (
    <Panel title="Tables Delta (miroirs)" sub="Écrites par le job d'entraînement ; métadonnées Unity Catalog uniquement, sans SQL warehouse">
      {tables.loading && <Loading />}
      {tables.error && <Unavailable tone="red">Métadonnées indisponibles : {tables.error}</Unavailable>}
      <div style={grid(320)}>
        {tables.data?.map((t) => (
          <div key={t.name} className="col" style={{ gap: 6, padding: 14, borderRadius: 14, background: 'var(--surface-soft)', minWidth: 0 }}>
            <b style={{ overflowWrap: 'anywhere' }}>{t.name}</b>
            <span className="muted" style={{ fontSize: 13 }}>{t.num_rows != null ? `${t.num_rows} lignes` : 'nombre de lignes non renseigné'} · dernière écriture {t.last_commit ? dateTime(t.last_commit) : '—'}</span>
            <span style={{ fontSize: 13, overflowWrap: 'anywhere' }}>{t.columns.map((c) => `${c.name} (${c.type})`).join(', ')}</span>
          </div>
        ))}
      </div>
      <span className="muted" style={{ fontSize: 13 }}>
        Ces tables reflètent le dernier entraînement ; elles ne sont pas l'historique des versions. Le prochain entraînement les écrira version par version, sans écraser les autres (déploiement du code distant prévu avec DBX-05).
      </span>
    </Panel>
  );
}

const th = { textAlign: 'left' as const, padding: '6px 10px', borderBottom: '1px solid var(--line-strong)', fontWeight: 700 };
const td = { padding: '6px 10px', borderBottom: '1px solid var(--line)' };
