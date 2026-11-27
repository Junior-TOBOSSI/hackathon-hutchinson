import { useState } from 'react';
import { defaultCondition, retraining, type Condition, type ConditionKind, type ModelOption, type Policy, type PolicyInput } from '../../../../api/retraining';
import { Unavailable } from '../../common';
import { errText, useDatasetFamily } from '../../data';
import { Chip, SelectField } from '../../ui';
import { CONDITION_LABEL, USE_CASES } from './shared';

const KINDS: ConditionKind[] = ['drift', 'annotations', 'performance', 'schedule', 'manual'];

const empty = (o: ModelOption[]): PolicyInput => ({
  name: '', use_case: o[0]?.use_case ?? 'quality', model_id: '', pipeline_id: '', dataset_family: '',
  dataset_selection: { strategy: 'latest_published', pinned_version: null }, active: false, mode: 'manual', logic: 'OR',
  conditions: KINDS.map(defaultCondition),
  guardrails: { max_runs_per_month: 2, min_hours_between: 72, allowed_hours: null, cpu_only: true, allow_concurrent: false }, comment: null,
});

/** Création ou modification (toute modification crée une NOUVELLE version côté serveur). */
export default function PolicyForm({ options, current, onSaved, onCancel }: {
  options: ModelOption[]; current: Policy | null; onSaved: (p: Policy) => void; onCancel: () => void;
}) {
  const start: PolicyInput = current
    ? { ...current, conditions: KINDS.map((k) => current.conditions.find((c) => c.kind === k) ?? defaultCondition(k)) }
    : empty(options);
  const [f, setF] = useState<PolicyInput>(start);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const set = (patch: Partial<PolicyInput>) => setF((x) => ({ ...x, ...patch }));
  const setCond = (kind: ConditionKind, patch: Partial<Condition>) =>
    setF((x) => ({ ...x, conditions: x.conditions.map((c) => (c.kind === kind ? { ...c, ...patch } : c)) }));

  const models = options.filter((m) => m.use_case === f.use_case);
  const model = models.find((m) => m.model_id === f.model_id);
  const pipeline = model?.pipelines.find((p) => p.pipeline_id === f.pipeline_id);
  const family = useDatasetFamily(f.dataset_family || null);
  const versions = (family.data?.versions ?? []).map((v) => v.version);
  const active = f.conditions.filter((c) => c.enabled);
  const hours = f.guardrails.allowed_hours;

  const save = async () => {
    setBusy(true);
    setError('');
    try {
      onSaved(current ? await retraining.update(current.policy_id, f) : await retraining.create(f));
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const num = (v: string, min: number) => Math.max(min, Number(v) || min);

  return (
    <div className="col" style={{ gap: 14 }}>
      {current && <div className="pol-note">Modifier crée la version v{current.version + 1} ; la version v{current.version} et son historique sont conservés.</div>}
      <div className="tf-params">
        <label>Nom<input value={f.name} maxLength={120} onChange={(e) => set({ name: e.target.value })} placeholder="ex. Qualité 702 — nouvelles annotations" /></label>
        <div className="pol-field"><span>Cas d’usage</span><SelectField label="Cas d’usage" icon="none" value={f.use_case} onChange={(v) => set({ use_case: v, model_id: '', pipeline_id: '', dataset_family: '' })} options={USE_CASES} /></div>
        <div className="pol-field"><span>Modèle</span><SelectField label="Modèle" icon="none" allLabel="Choisir…" value={f.model_id} onChange={(v) => set({ model_id: v, pipeline_id: '', dataset_family: '' })}
          options={models.map((m) => [m.model_id, m.name])} /></div>
        <div className="pol-field"><span>Pipeline</span><SelectField label="Pipeline" icon="none" allLabel={model && !model.pipelines.length ? 'Aucun pipeline livré' : 'Choisir…'} value={f.pipeline_id}
          onChange={(v) => set({ pipeline_id: v, dataset_family: '' })} options={(model?.pipelines ?? []).map((p) => [p.pipeline_id, p.name])} /></div>
        <div className="pol-field"><span>Famille de datasets</span><SelectField label="Famille" icon="none" allLabel="Choisir…" value={f.dataset_family}
          onChange={(v) => set({ dataset_family: v, dataset_selection: { strategy: 'latest_published', pinned_version: null } })} options={(pipeline?.families ?? []).map((x) => [x, x])} /></div>
        <div className="pol-field"><span>Sélection de la version</span><SelectField label="Sélection" icon="none" value={f.dataset_selection.strategy}
          onChange={(v) => set({ dataset_selection: { strategy: v as 'pinned', pinned_version: v === 'pinned' ? versions[versions.length - 1] ?? null : null } })}
          options={[['latest_published', 'Dernière version publiée'], ['pinned', 'Version épinglée']]} /></div>
        {f.dataset_selection.strategy === 'pinned' && <div className="pol-field"><span>Version épinglée</span><SelectField label="Version" icon="none" value={f.dataset_selection.pinned_version ?? ''}
          onChange={(v) => set({ dataset_selection: { strategy: 'pinned', pinned_version: v } })} options={versions.map((v) => [v, v])} /></div>}
      </div>
      {pipeline && <span className="muted" style={{ fontSize: 13 }}>Code scientifique figé à l’enregistrement : <code>{pipeline.code_version ?? 'inconnu'}</code>. Un changement de code exigera une nouvelle version de politique.</span>}

      <div className="pol-row">
        <SelectField label="Mode" icon="none" value={f.mode} onChange={(v) => set({ mode: v as 'manual' })} options={[['manual', 'Manuel (proposition à valider)'], ['auto', 'Automatique (planificateur)']]} />
        <SelectField label="Combinaison" icon="none" value={f.logic} onChange={(v) => set({ logic: v as 'OR' })} options={[['OR', 'OU : une condition suffit'], ['AND', 'ET : toutes les conditions']]} />
        <label className="pol-check"><input type="checkbox" checked={f.active} onChange={(e) => set({ active: e.target.checked })} />Politique active</label>
      </div>
      {f.mode === 'auto' && <div className="pol-note">Le mode automatique ne lance que si le planificateur est activé (HOVIS_RETRAIN_SCHEDULER) et que le verrou distant l’autorise (HOVIS_TRAINING_REMOTE). Le candidat produit n’est jamais approuvé ni déployé automatiquement.</div>}

      <h3 className="pol-h3">Conditions de déclenchement</h3>
      <div className="col" style={{ gap: 8 }}>
        {f.conditions.map((c) => (
          <div key={c.kind} className={`pol-cond${c.enabled ? ' on' : ''}`}>
            <label className="pol-check"><input type="checkbox" checked={c.enabled} onChange={(e) => setCond(c.kind, { enabled: e.target.checked })} /><b>{CONDITION_LABEL[c.kind]}</b></label>
            {c.enabled && f.logic === 'OR' && <label className="pol-check"><input type="checkbox" checked={c.required} onChange={(e) => setCond(c.kind, { required: e.target.checked })} />requise</label>}
            {c.enabled && c.kind === 'drift' && <>
              <label>Fenêtres distinctes<input type="number" min={2} max={30} value={c.drift.min_windows} onChange={(e) => setCond('drift', { drift: { ...c.drift, min_windows: num(e.target.value, 2) } })} /></label>
              <SelectField label="Niveau" icon="none" value={c.drift.min_level} onChange={(v) => setCond('drift', { drift: { ...c.drift, min_level: v as 'alert' } })} options={[['alert', 'Alerte'], ['watch', 'À surveiller']]} />
              <label className="pol-check"><input type="checkbox" checked={c.drift.allowed_origins.includes('simulated')}
                onChange={(e) => setCond('drift', { drift: { ...c.drift, allowed_origins: e.target.checked ? ['real', 'simulated'] : ['real'] } })} />inclure les données simulées (ne lancera jamais de calcul réel)</label>
            </>}
            {c.enabled && c.kind === 'annotations' && <label>Minimum de nouvelles annotations<input type="number" min={1} value={c.annotations.min_new} onChange={(e) => setCond('annotations', { annotations: { min_new: num(e.target.value, 1) } })} /></label>}
            {c.enabled && c.kind === 'performance' && <>
              <label>Métrique<input value={c.performance.metric} onChange={(e) => setCond('performance', { performance: { ...c.performance, metric: e.target.value } })} /></label>
              <label>Baisse maximale<input type="number" step="0.01" min={0.01} max={1} value={c.performance.max_drop} onChange={(e) => setCond('performance', { performance: { ...c.performance, max_drop: Number(e.target.value) || 0.05 } })} /></label>
              <Chip tone="amber">Indisponible sans vérité terrain de production</Chip>
            </>}
            {c.enabled && c.kind === 'schedule' && <label>Intervalle (jours)<input type="number" min={1} max={365} value={c.schedule.interval_days} onChange={(e) => setCond('schedule', { schedule: { interval_days: num(e.target.value, 1) } })} /></label>}
            {c.enabled && c.kind === 'manual' && <span className="muted" style={{ fontSize: 13 }}>Satisfaite par une demande explicite de l’AI Leader.</span>}
          </div>
        ))}
      </div>
      {!active.length && <Unavailable tone="grey">Aucune condition active : cette politique ne déclenchera jamais d’entraînement.</Unavailable>}

      <h3 className="pol-h3">Garde-fous</h3>
      <div className="tf-params">
        <label>Runs maximum par mois<input type="number" min={0} max={100} value={f.guardrails.max_runs_per_month} onChange={(e) => set({ guardrails: { ...f.guardrails, max_runs_per_month: num(e.target.value, 0) } })} /></label>
        <label>Délai minimal entre deux entraînements (h)<input type="number" min={0} value={f.guardrails.min_hours_between} onChange={(e) => set({ guardrails: { ...f.guardrails, min_hours_between: num(e.target.value, 0) } })} /></label>
        <div className="pol-field"><span>Plage horaire</span><SelectField label="Plage horaire" icon="none" value={hours ? 'window' : 'any'} onChange={(v) => set({ guardrails: { ...f.guardrails, allowed_hours: v === 'any' ? null : [20, 6] } })}
          options={[['any', 'Toute heure'], ['window', 'Plage définie']]} /></div>
        {hours && <>
          <label>Début (h)<input type="number" min={0} max={23} value={hours[0]} onChange={(e) => set({ guardrails: { ...f.guardrails, allowed_hours: [Math.min(23, num(e.target.value, 0)), hours[1]] } })} /></label>
          <label>Fin (h, exclue)<input type="number" min={0} max={24} value={hours[1]} onChange={(e) => set({ guardrails: { ...f.guardrails, allowed_hours: [hours[0], Math.min(24, num(e.target.value, 0))] } })} /></label>
        </>}
      </div>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}><Chip tone="navy">CPU uniquement</Chip><Chip tone="navy">Pas d’entraînement concurrent</Chip><Chip tone="navy">Verrou distant</Chip><Chip tone="navy">Idempotence persistante</Chip></div>
      <label className="pol-comment">Commentaire de version<input value={f.comment ?? ''} maxLength={500} onChange={(e) => set({ comment: e.target.value || null })} /></label>
      {error && <Unavailable tone="red">{error}</Unavailable>}
      <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
        <button className="btn btn-ghost" onClick={onCancel} disabled={busy}>Annuler</button>
        <button className="btn btn-primary" onClick={save} disabled={busy || !f.name.trim() || !f.model_id || !f.pipeline_id || !f.dataset_family}>
          {current ? `Enregistrer la version v${current.version + 1}` : 'Créer la politique'}
        </button>
      </div>
    </div>
  );
}
