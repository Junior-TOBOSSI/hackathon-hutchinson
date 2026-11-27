import { useEffect, useRef, useState } from 'react';
import { mlops, type DatasetFamilySummary, type DatasetIndex, type Draft, type ImportResult, type PublishJob } from '../../api/mlops';
import { Badge, grid, KV, Loading, Panel, Technical, Unavailable } from './common';
import DatasetExplorer, { isEvaluation, SPLIT_FR } from './DatasetExplorer';
import { errText, useFamilyDraft, useStore } from './data';
import { translate } from './messages';
import { dateTime } from './metrics';

/* Brouillon d'une nouvelle version : modifications d'annotations, import borné de
   données synthétiques, puis publication immuable suivie en temps réel.
   Aucune publication ne déclenche d'entraînement. */

const BATCH = 5; // files per import request: real progress, bounded memory
const PHASE_FR: Record<string, string> = {
  starting: 'démarrage', lock: 'verrouillage de la version', copy: 'copie des images', verify: 'vérification des empreintes SHA-256',
  manifest: 'écriture du manifeste (en dernier)', done: 'terminée',
};
const jobError = (e: string | null) => (e ? translate(e.replace(/^\w+: /, '')) : '');

export default function DatasetDraft({ modelId, draftId, index, family, resumeVersion, onPublished, onClose }: {
  modelId: string; draftId: string; index: DatasetIndex; family: DatasetFamilySummary; resumeVersion?: string | null;
  onPublished: (version: string) => void; onClose: () => void;
}) {
  const store = useStore();
  const draft = useFamilyDraft(modelId, draftId);
  const [message, setMessage] = useState('');
  const [showParent, setShowParent] = useState(false);
  const d = draft.data;
  const parent = index.versions.find((v) => v.version === d?.parent_version) ?? null;

  if (draft.loading) return <Panel title="Brouillon"><Loading /></Panel>;
  if (draft.error || !d) return <Panel title="Brouillon"><Unavailable tone="red">Brouillon indisponible : {draft.error}</Unavailable></Panel>;

  const changes = Object.entries(d.changes);
  const count = (a: string) => changes.filter(([, c]) => c.action === a).length;
  const evaluationTouched = [
    ...changes.filter(([file]) => isEvaluation(file.split('/')[0])).map(([file, c]) => `${file} (${c.action})`),
    ...d.imports.filter((i) => isEvaluation(i.split)).map((i) => `${i.original_name} (import en ${SPLIT_FR[i.split]})`),
  ];
  const refresh = () => store.invalidate(`family-draft:${modelId}:${draftId}`, `family:${modelId}`, 'dataset-catalog');
  const remove = async () => {
    if (!window.confirm('Supprimer ce brouillon ? Les versions publiées ne sont pas concernées.')) return;
    try {
      await mlops.deleteFamilyDraft(modelId, draftId);
      store.invalidate(`family:${modelId}`, 'dataset-catalog');
      onClose();
    } catch (e) {
      setMessage(errText(e));
    }
  };

  return (
    <>
      <Panel title={d.parent_version ? `Brouillon à partir de ${d.parent_version}` : 'Brouillon de la première version'}
        sub={`Créé le ${dateTime(d.created_at)} · modifié le ${dateTime(d.updated_at)}`}
        right={<div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <Badge tone={d.status === 'open' ? 'blue' : d.status === 'published' ? 'green' : 'amber'}>{d.status === 'open' ? 'brouillon ouvert' : d.status === 'published' ? `publié : ${d.published_version}` : `publication en cours : ${d.target_version}`}</Badge>
          {d.status !== 'publishing' && <button className="btn btn-ghost" style={{ height: 36 }} onClick={remove}>Supprimer le brouillon</button>}
          <button className="btn btn-ghost" style={{ height: 36 }} onClick={onClose}>Fermer</button>
        </div>}>
        <div style={grid(170)}>
          <Fact label="Annotations validées" value={count('validate')} />
          <Fact label="Labels corrigés" value={count('relabel')} />
          <Fact label="Éléments exclus" value={count('exclude')} />
          <Fact label="Images importées" value={d.imports.length} />
        </div>
        {!d.parent_version
          ? <span className="muted" style={{ fontSize: 14 }}>Première version : les images importées reçoivent explicitement leur classe et leur split.</span>
          : evaluationTouched.length > 0
          ? <Unavailable>Changement de la référence d'évaluation : {evaluationTouched.length} modification(s) touchent la validation ou le test ({evaluationTouched.slice(0, 3).join(', ')}{evaluationTouched.length > 3 ? '…' : ''}). Les évaluations de la nouvelle version ne seront pas comparables à celles de {d.parent_version} ; ce changement sera signalé dans le manifeste.</Unavailable>
          : <span className="muted" style={{ fontSize: 14 }}>Les jeux de validation et de test restent identiques à {d.parent_version} : les évaluations resteront comparables.</span>}
        {message && <Unavailable tone="red">{message}</Unavailable>}
        <Technical title="Identifiants du brouillon"><KV k="brouillon" v={d.draft_id} /><KV k="manifeste parent (SHA-256)" v={d.parent_manifest_sha256} /></Technical>
      </Panel>

      {d.status === 'open' && <ImportPanel modelId={modelId} draft={d} classes={parent?.classes ?? family.classes} onDone={refresh} />}
      {parent && <div><button className="btn btn-ghost" onClick={() => setShowParent((value) => !value)}>
        {showParent ? 'Masquer' : 'Annoter'} les images de la version parente
      </button></div>}
      {parent && showParent && <DatasetExplorer modelId={modelId} version={parent.version} classes={parent.classes} draft={d} />}
      {d.imports.length > 0 && (
        <Panel title="Images importées (en attente de publication)">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
            {d.imports.map((i) => (
              <div key={i.sha256} className="col" style={{ gap: 4, padding: 6, borderRadius: 12, border: '1px solid var(--line)' }}>
                <span style={{ fontSize: 12, overflowWrap: 'anywhere' }}>{i.original_name}</span>
                <div className="row" style={{ gap: 4, flexWrap: 'wrap' }}><Badge tone={i.label === 'NOK' ? 'red' : 'green'}>{i.label}</Badge><Badge tone={isEvaluation(i.split) ? 'blue' : 'grey'}>{SPLIT_FR[i.split]}</Badge></div>
                {d.status === 'open' && <button className="btn" style={{ background: 'none', color: 'var(--primary)', padding: 0, height: 'auto', fontSize: 13 }}
                  onClick={() => mlops.removeFamilyImport(modelId, d.draft_id, i.sha256).then(refresh).catch((e) => setMessage(errText(e)))}>Retirer</button>}
              </div>
            ))}
          </div>
        </Panel>
      )}

      {d.status !== 'published' && <PublishPanel modelId={modelId} draft={d} index={index} initialVersion={`${family.dataset_id.slice(0, 38)}-v1`} resumeVersion={resumeVersion} onPublished={onPublished} />}
    </>
  );
}

function ImportPanel({ modelId, draft, classes, onDone }: { modelId: string; draft: Draft; classes: string[]; onDone: () => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [label, setLabel] = useState('');
  const [split, setSplit] = useState('');
  const [attested, setAttested] = useState(false);
  const [progress, setProgress] = useState<{ sent: number; total: number } | null>(null);
  const [results, setResults] = useState<ImportResult[]>([]);
  const [error, setError] = useState('');
  const tooMany = files.length > 50;

  const run = async () => {
    setError(''); setResults([]);
    const all: ImportResult[] = [];
    setProgress({ sent: 0, total: files.length });
    try {
      for (let i = 0; i < files.length; i += BATCH) {
        const batch = files.slice(i, i + BATCH);
        all.push(...await mlops.importFamilyFiles(modelId, draft.draft_id, batch, label, split, attested));
        setProgress({ sent: Math.min(i + BATCH, files.length), total: files.length });
        setResults([...all]);
      }
      setFiles([]);
    } catch (e) {
      setError(`${errText(e)} — ${all.filter((r) => r.accepted).length} fichier(s) déjà importé(s) avant l'erreur.`);
    } finally {
      setProgress(null);
      onDone();
    }
  };

  return (
    <Panel title="Importer des images synthétiques" sub="PNG ou JPEG · 2 Mo et 4096 px au maximum par fichier · 50 fichiers au maximum · aucune annotation automatique">
      <div className="row" style={{ gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <input type="file" accept="image/png,image/jpeg" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        <label className="row" style={{ gap: 6, fontSize: 14 }}><span className="muted">Classe</span>
          <select value={label} onChange={(e) => setLabel(e.target.value)} style={{ height: 36, borderRadius: 10 }}><option value="">— choisir —</option>{classes.map((c) => <option key={c}>{c}</option>)}</select></label>
        <label className="row" style={{ gap: 6, fontSize: 14 }}><span className="muted">Split</span>
          <select value={split} onChange={(e) => setSplit(e.target.value)} style={{ height: 36, borderRadius: 10 }}><option value="">— choisir —</option>{['train', 'validation', 'test'].map((s) => <option key={s} value={s}>{SPLIT_FR[s]}</option>)}</select></label>
      </div>
      {isEvaluation(split) && <Unavailable>Ajouter des images en {SPLIT_FR[split]} change la référence d'évaluation.</Unavailable>}
      <label className="row" style={{ gap: 8, fontSize: 14, alignItems: 'flex-start' }}>
        <input type="checkbox" checked={attested} onChange={(e) => setAttested(e.target.checked)} />
        <span>J'atteste que ces images sont <b>synthétiques</b>, sans visage ni donnée industrielle réelle. <span className="muted">(Déclaration : le contenu des images n'est pas vérifiable techniquement.)</span></span>
      </label>
      {tooMany && <Unavailable tone="red">{files.length} fichiers sélectionnés : 50 au maximum par envoi.</Unavailable>}
      <div className="row" style={{ gap: 12, alignItems: 'center' }}>
        <button className="btn btn-primary" style={{ height: 40 }} disabled={!files.length || !label || !split || !attested || tooMany || !!progress} onClick={run}>
          Importer {files.length ? `${files.length} fichier(s)` : ''} dans le brouillon
        </button>
        {progress && <ProgressBar done={progress.sent} total={progress.total} label={`${progress.sent} / ${progress.total} envoyé(s) et vérifié(s)`} />}
      </div>
      {error && <Unavailable tone="red">{error}</Unavailable>}
      {results.length > 0 && (
        <div className="col" style={{ gap: 2, fontSize: 13 }}>
          <b>{results.filter((r) => r.accepted).length} accepté(s), {results.filter((r) => !r.accepted).length} refusé(s)</b>
          {results.filter((r) => !r.accepted).map((r, i) => <span key={i} style={{ color: 'var(--red-dark)' }}>{r.name} : {translate(r.reason ?? '')}</span>)}
        </div>
      )}
    </Panel>
  );
}

function PublishPanel({ modelId, draft, index, initialVersion, resumeVersion, onPublished }: { modelId: string; draft: Draft; index: DatasetIndex; initialVersion: string; resumeVersion?: string | null; onPublished: (v: string) => void }) {
  const store = useStore();
  const resuming = draft.status === 'publishing';
  const [version, setVersion] = useState(resuming ? draft.target_version ?? '' : resumeVersion ?? (draft.parent_version ? suggest(draft.parent_version, index) : initialVersion));
  const [job, setJob] = useState<PublishJob | null>(null);
  const [error, setError] = useState('');
  const timer = useRef<number | null>(null);
  const empty = Object.keys(draft.changes).length === 0 && draft.imports.length === 0;
  const exists = index.versions.some((v) => v.version === version);

  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);

  const follow = (started: PublishJob) => {
    setJob(started);
    timer.current = window.setInterval(async () => {
      try {
        const j = await mlops.datasetJob(started.job_id);
        setJob(j);
        if (j.state !== 'running') {
          if (timer.current) window.clearInterval(timer.current);
          store.invalidate(`family:${modelId}`, `family-draft:${modelId}:${draft.draft_id}`, 'dataset-catalog');
          if (j.state === 'succeeded') onPublished(j.version);
        }
      } catch (e) {
        setError(errText(e));
      }
    }, 1000);
  };

  const publish = async () => {
    const what = resuming ? `Reprendre la publication de « ${version} » ?` : `Publier la version « ${version} » ?`;
    if (!window.confirm(`${what}\n\nLa version sera immuable (jamais réécrite par HOVIS) : copie des images, vérification de chaque empreinte SHA-256, puis écriture du manifeste en dernier.\nAucun entraînement ne sera lancé.`)) return;
    setError('');
    try {
      follow(await mlops.publishFamilyDraft(modelId, draft.draft_id, version));
    } catch (e) {
      setError(errText(e));
    }
  };

  const running = job?.state === 'running';
  return (
    <Panel title={resuming ? 'Reprendre la publication interrompue' : 'Publier une nouvelle version'}
      sub="Une version publiée n'est jamais réécrite ; la publication ne déclenche aucun entraînement.">
      {resuming && !job && <Unavailable>Publication de « {draft.target_version} » interrompue : le dossier existe sans manifeste, il n'est donc pas une version. La reprise vérifie les fichiers déjà copiés et n'écrase rien.</Unavailable>}
      <div className="row" style={{ gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <label className="row" style={{ gap: 6, fontSize: 14 }}><span className="muted">Nom de la version</span>
          <input value={version} disabled={resuming || running} onChange={(e) => setVersion(e.target.value.trim())} maxLength={41} style={{ height: 38, padding: '0 10px', borderRadius: 10, border: '1px solid var(--line-strong)' }} /></label>
        <button className="btn btn-primary" style={{ height: 40 }} disabled={empty || exists || !version || running || job?.state === 'succeeded'} onClick={publish}>
          {resuming ? 'Reprendre la publication' : 'Publier la version'}
        </button>
      </div>
      {empty && <span className="muted" style={{ fontSize: 14 }}>Rien à publier : le brouillon ne contient aucune modification.</span>}
      {exists && <Unavailable tone="red">La version {version} existe déjà : choisir un autre nom.</Unavailable>}
      {job && (
        <div className="col" style={{ gap: 6 }}>
          <ProgressBar done={job.done} total={Math.max(job.total, 1)} label={`${PHASE_FR[job.phase] ?? job.phase}${job.total ? ` · ${job.done} / ${job.total}` : ''}`} />
          {job.state === 'succeeded' && <Unavailable tone="grey">Version {job.version} publiée et vérifiée (manifeste {job.manifest_sha256?.slice(0, 12)}…). Aucun entraînement n'a été lancé.</Unavailable>}
          {job.state === 'failed' && <Unavailable tone="red">Publication interrompue : {jobError(job.error)}. Le dossier n'est pas une version (aucun manifeste) ; la reprise est possible depuis ce brouillon.</Unavailable>}
        </div>
      )}
      {error && <Unavailable tone="red">{error}</Unavailable>}
    </Panel>
  );
}

function suggest(parent: string, index: DatasetIndex): string {
  const m = parent.match(/^(.*-v)(\d+)$/);
  const taken = new Set([...index.versions.map((v) => v.version), ...index.incomplete.map((v) => v.version)]);
  if (!m) return '';
  for (let n = Number(m[2]) + 1; n < 1000; n += 1) if (!taken.has(`${m[1]}${n}`)) return `${m[1]}${n}`;
  return '';
}

export function ProgressBar({ done, total, label }: { done: number; total: number; label: string }) {
  const pct = Math.round((Math.min(done, total) / total) * 100);
  return (
    <div className="col" style={{ gap: 4, minWidth: 260, flex: 1 }}>
      <div style={{ height: 10, borderRadius: 6, background: 'var(--track)', overflow: 'hidden' }}><div style={{ width: `${pct}%`, height: '100%', background: 'var(--primary)', transition: 'width .3s' }} /></div>
      <span className="muted" style={{ fontSize: 13 }}>{label}</span>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: number }) {
  return <div className="col" style={{ gap: 2 }}><span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>{label}</span><span className="num" style={{ fontSize: 26 }}>{value}</span></div>;
}
