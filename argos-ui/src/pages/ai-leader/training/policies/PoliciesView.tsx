import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { retraining, type Evaluation, type Policy, type Proposal } from '../../../../api/retraining';
import { training } from '../../../../api/training';
import { Loading, Unavailable } from '../../common';
import { errText, useStore } from '../../data';
import { Chip, Kpi } from '../../ui';
import { dt } from '../shared';
import PolicyForm from './PolicyForm';
import './policies.css';
import {
  CONDITION_LABEL, fr, GUARD_LABEL, ProposalChip, StateChip, useAudit, useCaseFr, useEvaluations, usePolicies, usePolicy,
  useProposals, useRetrainKpis, useRetrainOptions,
} from './shared';

type Tab = 'config' | 'evaluation' | 'proposals' | 'history' | 'audit';
const TABS: [Tab, string][] = [['config', 'Configuration'], ['evaluation', 'Évaluation'], ['proposals', 'Propositions'], ['history', 'Historique'], ['audit', 'Journal d’audit']];

/** URL: ?section=training&view=policies&policy=<id>&ptab=<tab> | &pnew=1 (&model=<id> = filter from Monitoring). */
function usePolParams() {
  const [params, setParams] = useSearchParams();
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) if (v) next.set(k, v); else next.delete(k);
    setParams(next);
  };
  return { policy: params.get('policy'), isNew: params.get('pnew') === '1', tab: (params.get('ptab') ?? 'config') as Tab, model: params.get('model'), set };
}

/* Politiques de réentraînement (DBX-08B) : KPI, catalogue, configuration versionnée,
   évaluation explicite, propositions, historique et journal. Aucun lancement hors
   TrainingService.launch ; approbation et déploiement restent humains. */
export default function PoliciesView() {
  const store = useStore();
  const nav = usePolParams();
  const kpis = useRetrainKpis();
  const options = useRetrainOptions();
  const policies = usePolicies();
  const proposals = useProposals();
  const k = kpis.data;
  const rows = (policies.data ?? []).filter((p) => !nav.model || p.model_id === nav.model);
  const panel = nav.isNew || !!nav.policy;
  const pending = (proposals.data ?? []).filter((p) => p.status === 'pending' || p.status === 'accepted' || p.status === 'uncertain');
  const modelName = (id: string) => options.data?.find((m) => m.model_id === id)?.name ?? id;

  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="pol-kpis">
        <Kpi icon="layers" label="Politiques" value={k ? k.policies : '…'} hint={k ? `${k.active} active(s) · ${k.auto} automatique(s)` : undefined} />
        <Kpi icon="flag" label="Propositions en attente" value={k ? k.pending_proposals : '…'} tone={k?.pending_proposals ? 'amber' : undefined}
          hint={k?.uncertain_proposals ? `${k.uncertain_proposals} réponse(s) incertaine(s) à réconcilier` : 'décision de l’AI Leader'} />
        <Kpi icon="play" label="Lancés ce mois-ci" value={k ? k.launched_this_month : '…'} hint="via TrainingService.launch" />
        <Kpi icon="log" label="Planificateur" value={k ? (k.scheduler.enabled ? 'Activé' : 'Désactivé') : '…'} tone={k?.scheduler.enabled ? 'amber' : undefined}
          hint={k ? `${k.scheduler.variable}${k.scheduler.last_tick ? ` · dernier passage ${dt(k.scheduler.last_tick)}` : ''}` : undefined} />
        <Kpi icon="key" label="Verrou distant" value={k ? (k.remote_launch_enabled ? 'Ouvert' : 'Fermé') : '…'} tone={k?.remote_launch_enabled ? 'red' : 'green'}
          hint="HOVIS_TRAINING_REMOTE : sans lui, aucun lancement" />
      </div>
      {kpis.error && <Unavailable tone="red">Indicateurs indisponibles : {kpis.error}</Unavailable>}

      <div className={`tf-layout${panel ? '' : ' full'}`}>
        <section className="card tf-panel tf-catalog">
          <div className="between" style={{ gap: 10, flexWrap: 'wrap' }}>
            <h2 className="h2" style={{ fontSize: 21 }}>Politiques de réentraînement</h2>
            <button className="btn btn-primary" onClick={() => nav.set({ pnew: '1', policy: null, ptab: null })}>＋ Nouvelle politique</button>
          </div>
          {nav.model && <div className="row" style={{ gap: 8 }}><Chip tone="blue">Modèle : {modelName(nav.model)}</Chip><button className="btn btn-ghost" style={{ height: 30 }} onClick={() => nav.set({ model: null })}>Tous les modèles</button></div>}
          {policies.loading && <Loading what="Lecture des politiques" />}
          {policies.error && <Unavailable tone="red">Politiques indisponibles : {policies.error}</Unavailable>}
          {policies.data && rows.length === 0 && <Unavailable tone="grey">Aucune politique{nav.model ? ' pour ce modèle' : ''}. Créez-en une : elle restera inactive tant que vous ne l’activez pas.</Unavailable>}
          {rows.length > 0 && <div className="tf-table-wrap"><table className="tf-table"><thead><tr>
            <th>Politique</th><th>Modèle · pipeline</th><th className="opt">Dataset</th><th>Mode</th><th className="opt">Conditions</th><th>État</th><th className="opt">Action</th>
          </tr></thead><tbody>{rows.map((p) => (
            <tr key={p.policy_id} className={nav.policy === p.policy_id ? 'selected' : ''} tabIndex={0} onClick={() => nav.set({ policy: p.policy_id, pnew: null })}
              onKeyDown={(e) => { if (e.key === 'Enter') nav.set({ policy: p.policy_id, pnew: null }); }}>
              <td><b>{p.name}</b><small>v{p.version} · {useCaseFr(p.use_case)}</small></td>
              <td>{modelName(p.model_id)}<small>{p.pipeline_id}</small></td>
              <td className="opt">{p.dataset_family}<small>{p.dataset_selection.strategy === 'pinned' ? `épinglée ${p.dataset_selection.pinned_version}` : 'dernière publiée'}</small></td>
              <td><Chip tone={p.mode === 'auto' ? 'navy' : 'grey'}>{p.mode === 'auto' ? 'Automatique' : 'Manuel'}</Chip></td>
              <td className="opt">{p.conditions.filter((c) => c.enabled).map((c) => CONDITION_LABEL[c.kind]).join(` ${p.logic === 'AND' ? 'ET' : 'OU'} `) || <span className="muted">aucune</span>}</td>
              <td>{p.active ? <Chip tone="green">Active</Chip> : <Chip tone="grey">Inactive</Chip>}</td>
              <td className="opt"><button className="btn btn-ghost" style={{ height: 34 }} onClick={(e) => { e.stopPropagation(); nav.set({ policy: p.policy_id, pnew: null }); }}>Ouvrir</button></td>
            </tr>))}</tbody></table></div>}

          <h3 className="pol-h3">Propositions à traiter</h3>
          {pending.length === 0 ? <span className="muted" style={{ fontSize: 14 }}>Aucune proposition en attente.</span>
            : pending.map((p) => <button key={p.proposal_id} className="pol-prop-link" onClick={() => nav.set({ policy: p.policy_id, ptab: 'proposals', pnew: null })}>
              <ProposalChip status={p.status} /> {modelName(p.model_id)} · {p.dataset_family} {p.dataset_version} <span className="muted">· {dt(p.created_at)}</span></button>)}
        </section>
        {nav.isNew && options.data && (
          <section className="card tf-panel">
            <div className="between"><h2 className="h2" style={{ fontSize: 21 }}>Nouvelle politique</h2><button className="btn btn-ghost" style={{ height: 34 }} onClick={() => nav.set({ pnew: null })}>×</button></div>
            <PolicyForm options={options.data} current={null} onCancel={() => nav.set({ pnew: null })}
              onSaved={(p) => { store.invalidate('ret:'); nav.set({ pnew: null, policy: p.policy_id, ptab: 'config' }); }} />
          </section>
        )}
        {!nav.isNew && nav.policy && <PolicyDetail key={nav.policy} id={nav.policy} tab={nav.tab} setTab={(t) => nav.set({ ptab: t })} onClose={() => nav.set({ policy: null, ptab: null })} />}
      </div>
    </div>
  );
}

function PolicyDetail({ id, tab, setTab, onClose }: { id: string; tab: Tab; setTab: (t: Tab) => void; onClose: () => void }) {
  const store = useStore();
  const res = usePolicy(id);
  const options = useRetrainOptions();
  const [editing, setEditing] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'red' | 'amber' | 'grey'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const p = res.data?.current;
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ tone: 'grey', text: ok });
      store.invalidate('ret:');
    } catch (e) {
      setMsg({ tone: 'red', text: errText(e) });
    } finally {
      setBusy(false);
    }
  };
  if (res.loading) return <section className="card tf-panel"><Loading /></section>;
  if (res.error || !p) return <section className="card tf-panel"><Unavailable tone="red">Politique indisponible : {res.error}</Unavailable></section>;
  return (
    <section className="card tf-panel">
      <div className="between" style={{ alignItems: 'flex-start', gap: 10 }}>
        <div className="col" style={{ gap: 6 }}>
          <h2 className="h2" style={{ fontSize: 21, margin: 0 }}>{p.name}</h2>
          <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            <Chip tone="blue">v{p.version}</Chip>{p.active ? <Chip tone="green">Active</Chip> : <Chip tone="grey">Inactive</Chip>}
            <Chip tone={p.mode === 'auto' ? 'navy' : 'grey'}>{p.mode === 'auto' ? 'Automatique' : 'Manuel'}</Chip><Chip tone="grey">{p.logic === 'AND' ? 'ET' : 'OU'}</Chip>
          </div>
        </div>
        <button className="btn btn-ghost" style={{ height: 34 }} onClick={onClose} aria-label="Fermer">×</button>
      </div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <button className="btn btn-ghost" disabled={busy} onClick={() => act(() => retraining.activate(p.policy_id, !p.active), p.active ? 'Politique désactivée (nouvelle version).' : 'Politique activée (nouvelle version).')}>{p.active ? 'Désactiver' : 'Activer'}</button>
        <button className="btn btn-ghost" disabled={busy} onClick={() => { setEditing(true); setTab('config'); }}>Modifier</button>
        <button className="btn btn-ghost" disabled={busy} onClick={() => act(async () => {
          const ev = await retraining.evaluate(p.policy_id);
          setTab('evaluation');
          return ev;
        }, 'Évaluation explicite enregistrée (aucun lancement).')}>Évaluer maintenant</button>
        {p.conditions.some((c) => c.kind === 'manual' && c.enabled) && <button className="btn btn-ghost" disabled={busy}
          onClick={() => { const note = window.prompt('Motif de la demande manuelle (facultatif)') ?? null; void act(() => retraining.manual(p.policy_id, note), 'Demande manuelle enregistrée : elle sera prise en compte à la prochaine évaluation.'); }}>Demande manuelle</button>}
      </div>
      {msg && <Unavailable tone={msg.tone}>{fr(msg.text)}</Unavailable>}
      <div className="tf-tabs">{TABS.map(([t, l]) => <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{l}</button>)}</div>
      {tab === 'config' && (editing && options.data
        ? <PolicyForm options={options.data} current={p} onCancel={() => setEditing(false)} onSaved={() => { setEditing(false); store.invalidate('ret:'); }} />
        : <ConfigView p={p} manual={res.data?.manual_requests.length ?? 0} />)}
      {tab === 'evaluation' && <EvaluationTab id={p.policy_id} />}
      {tab === 'proposals' && <ProposalsTab policy={p} />}
      {tab === 'history' && <div className="tf-table-wrap"><table className="tf-table"><thead><tr><th>Version</th><th>Date</th><th>État</th><th>Mode</th><th>Conditions</th><th>Code</th><th>Commentaire</th></tr></thead>
        <tbody>{(res.data?.history ?? []).map((h) => <tr key={h.version} className="static"><td>v{h.version}</td><td>{dt(h.created_at)}<small>{h.author}</small></td>
          <td>{h.active ? 'active' : 'inactive'}</td><td>{h.mode === 'auto' ? 'automatique' : 'manuel'} · {h.logic === 'AND' ? 'ET' : 'OU'}</td>
          <td>{h.conditions.filter((c) => c.enabled).map((c) => CONDITION_LABEL[c.kind]).join(', ') || '—'}</td><td><code>{h.code_version.slice(0, 10)}</code></td><td>{h.comment ?? '—'}</td></tr>)}</tbody></table></div>}
      {tab === 'audit' && <AuditTab id={p.policy_id} />}
    </section>
  );
}

function ConfigView({ p, manual }: { p: Policy; manual: number }) {
  const g = p.guardrails;
  return (
    <div className="col" style={{ gap: 12 }}>
      <dl className="pol-kv">
        <dt>Cas d’usage</dt><dd>{useCaseFr(p.use_case)}</dd>
        <dt>Modèle</dt><dd>{p.model_id}</dd>
        <dt>Pipeline</dt><dd>{p.pipeline_id} · code <code>{p.code_version.slice(0, 12)}</code></dd>
        <dt>Dataset</dt><dd>{p.dataset_family} · {p.dataset_selection.strategy === 'pinned' ? `version épinglée ${p.dataset_selection.pinned_version}` : 'dernière version publiée'}</dd>
        <dt>Combinaison</dt><dd>{p.logic === 'AND' ? 'ET : toutes les conditions actives' : 'OU : une condition suffit (les conditions requises restent obligatoires)'}</dd>
        <dt>Garde-fous</dt><dd>{g.max_runs_per_month} run(s)/mois · délai {g.min_hours_between} h · {g.allowed_hours ? `${g.allowed_hours[0]}h–${g.allowed_hours[1]}h` : 'toute heure'} · CPU · sans concurrence</dd>
        <dt>Demandes manuelles</dt><dd>{manual} en attente</dd>
      </dl>
      <div className="tf-table-wrap"><table className="tf-table"><thead><tr><th>Condition</th><th>Active</th><th>Paramètres</th></tr></thead><tbody>
        {p.conditions.map((c) => <tr key={c.kind} className="static"><td>{CONDITION_LABEL[c.kind]}{c.required && c.enabled && <small>requise</small>}</td>
          <td>{c.enabled ? <Chip tone="green">Oui</Chip> : <Chip tone="grey">Non</Chip>}</td>
          <td style={{ fontSize: 13 }}>{c.kind === 'drift' ? `${c.drift.min_windows} fenêtres distinctes ≥ ${c.drift.min_level === 'alert' ? 'alerte' : 'surveillance'} · origines ${c.drift.allowed_origins.join(', ')}`
            : c.kind === 'annotations' ? `≥ ${c.annotations.min_new} nouvelles annotations (train / validation)`
              : c.kind === 'performance' ? `${c.performance.metric} en baisse ≥ ${c.performance.max_drop}`
                : c.kind === 'schedule' ? `tous les ${c.schedule.interval_days} jours` : 'demande explicite'}</td></tr>)}
      </tbody></table></div>
    </div>
  );
}

function EvaluationView({ ev }: { ev: Evaluation }) {
  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {ev.eligible ? <Chip tone="amber">Éligible</Chip> : <Chip tone="grey">Non éligible</Chip>}
        <span style={{ fontSize: 14 }}>{fr(ev.reason)}</span>
        <span className="muted" style={{ fontSize: 13 }}>· {dt(ev.at)} · {ev.trigger === 'scheduler' ? 'planificateur' : 'explicite'} · v{ev.policy_version} · dataset cible {ev.target_dataset_version ?? '—'}</span>
      </div>
      <div className="tf-table-wrap"><table className="tf-table"><thead><tr><th>Condition</th><th>État</th><th>Raison</th></tr></thead><tbody>
        {ev.conditions.length === 0 && <tr className="static"><td colSpan={3} className="muted">Aucune condition active.</td></tr>}
        {ev.conditions.map((c) => <tr key={c.kind} className="static"><td>{CONDITION_LABEL[c.kind]}{c.required && <small>requise</small>}{c.simulated && <small>preuve simulée</small>}</td>
          <td><StateChip state={c.state} /></td><td style={{ fontSize: 13 }}>{fr(c.reason)}</td></tr>)}
      </tbody></table></div>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {ev.guards.map((g) => <Chip key={g.name} tone={g.ok ? 'green' : 'red'} title={fr(g.detail)}>{GUARD_LABEL[g.name] ?? g.name} {g.ok ? '✓' : '✗'}</Chip>)}
      </div>
      {ev.proposal_id && <Unavailable tone="grey">Proposition créée : {ev.proposal_id}</Unavailable>}
    </div>
  );
}

function EvaluationTab({ id }: { id: string }) {
  const evs = useEvaluations(id);
  if (evs.loading) return <Loading />;
  if (evs.error) return <Unavailable tone="red">Évaluations indisponibles : {evs.error}</Unavailable>;
  const [last, ...older] = evs.data ?? [];
  return (
    <div className="col" style={{ gap: 14 }}>
      {!last ? <Unavailable tone="grey">Aucune évaluation. « Évaluer maintenant » calcule les conditions sans jamais lancer d’entraînement.</Unavailable> : <EvaluationView ev={last} />}
      {older.length > 0 && <details><summary className="muted" style={{ cursor: 'pointer' }}>{older.length} évaluation(s) précédente(s)</summary>
        <div className="col" style={{ gap: 6, marginTop: 8 }}>{older.map((e) => <span key={e.evaluation_id} style={{ fontSize: 13 }}>{dt(e.at)} · {e.eligible ? 'éligible' : 'non éligible'} · {fr(e.reason)}</span>)}</div></details>}
    </div>
  );
}

function ProposalsTab({ policy }: { policy: Policy }) {
  const store = useStore();
  const all = useProposals();
  const [check, setCheck] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ tone: 'red' | 'grey'; text: string } | null>(null);
  const mine = (all.data ?? []).filter((p) => p.policy_id === policy.policy_id);
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try {
      await fn();
      setMsg({ tone: 'grey', text: ok });
    } catch (e) {
      setMsg({ tone: 'red', text: errText(e) });
    } finally {
      store.invalidate('ret:', 'training:');
    }
  };
  const verify = async (p: Proposal) => {
    try {
      const r = await training.validate({ pipeline_id: p.pipeline_id, dataset_id: p.dataset_family, version: p.dataset_version, parameters: {} });
      setCheck((c) => ({ ...c, [p.proposal_id]: r.launchable ? 'Pipeline et dataset compatibles : contrôles bloquants satisfaits.'
        : `Contrôles bloquants en échec : ${r.checks.filter((x) => x.status === 'error').map((x) => x.label).join(', ')}` }));
    } catch (e) {
      setCheck((c) => ({ ...c, [p.proposal_id]: `Vérification impossible : ${errText(e)}` }));
    }
  };
  if (all.loading) return <Loading />;
  if (!mine.length) return <Unavailable tone="grey">Aucune proposition : une évaluation éligible d’une politique active en crée une (une seule par preuve).</Unavailable>;
  return (
    <div className="col" style={{ gap: 12 }}>
      {msg && <Unavailable tone={msg.tone}>{fr(msg.text)}</Unavailable>}
      {mine.map((p) => (
        <div key={p.proposal_id} className="tf-box">
          <div className="between" style={{ gap: 8, flexWrap: 'wrap' }}>
            <span className="row" style={{ gap: 8 }}><ProposalChip status={p.status} /><b>{p.pipeline_id}</b> · {p.dataset_family} {p.dataset_version}</span>
            <span className="muted" style={{ fontSize: 13 }}>{dt(p.created_at)} · v{p.policy_version}{p.job_run_id ? ` · job run ${p.job_run_id}` : ''}</span>
          </div>
          <ul className="pol-reasons">{p.reasons.map((r) => <li key={r}>{fr(r)}</li>)}</ul>
          {p.simulated && <Unavailable>Preuve simulée : ne lancera jamais de calcul réel.</Unavailable>}
          {p.last_error && <Unavailable tone="red">Dernier refus : {fr(p.last_error)}</Unavailable>}
          {check[p.proposal_id] && <Unavailable tone="grey">{check[p.proposal_id]}</Unavailable>}
          {p.decided_by && <span className="muted" style={{ fontSize: 13 }}>Décision : {p.decided_by}{p.decision_note ? ` — ${p.decision_note}` : ''}</span>}
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-ghost" onClick={() => verify(p)}>Vérifier pipeline et dataset</button>
            {(p.status === 'pending' || p.status === 'accepted') && <>
              <button className="btn btn-primary" onClick={() => {
                if (!window.confirm(`Accepter et lancer l’entraînement ?\n\n${p.pipeline_id} sur ${p.dataset_family} ${p.dataset_version}\nLancement par TrainingService.launch (verrou, contrôles, budget, délai). Le modèle produit restera candidat : ni alias, ni approbation, ni déploiement automatiques.`)) return;
                void run(() => retraining.accept(p.proposal_id, null), 'Proposition acceptée et entraînement lancé.');
              }}>Accepter et lancer</button>
              {p.status === 'pending' && <button className="btn btn-ghost" onClick={() => {
                const note = window.prompt('Motif du refus (facultatif)');
                if (note === null) return;
                void run(() => retraining.reject(p.proposal_id, note || null), 'Proposition refusée.');
              }}>Refuser</button>}
            </>}
            {p.status === 'uncertain' && <button className="btn btn-ghost" onClick={() => run(() => retraining.reconcile(p.proposal_id), 'Réconciliation effectuée (même clé d’idempotence).')}>Réconcilier</button>}
          </div>
        </div>
      ))}
    </div>
  );
}

function AuditTab({ id }: { id: string }) {
  const audit = useAudit(id);
  if (audit.loading) return <Loading />;
  if (audit.error) return <Unavailable tone="red">Journal indisponible : {audit.error}</Unavailable>;
  const EVENTS: Record<string, string> = {
    'policy.created': 'Politique créée', 'policy.updated': 'Nouvelle version', 'policy.activated': 'Activée', 'policy.deactivated': 'Désactivée',
    'policy.evaluated': 'Évaluation', 'manual.requested': 'Demande manuelle', 'proposal.created': 'Proposition créée', 'proposal.accepted': 'Proposition acceptée',
    'proposal.rejected': 'Proposition refusée', 'launch.reserved': 'Budget réservé', 'launch.submitted': 'Entraînement lancé', 'launch.refused': 'Lancement refusé',
    'launch.uncertain': 'Réponse incertaine',
  };
  return (
    <div className="tf-table-wrap"><table className="tf-table"><thead><tr><th>Date</th><th>Acteur</th><th>Événement</th><th>Détail</th></tr></thead>
      <tbody>{(audit.data ?? []).map((e) => {
        const { id: _i, at, policy_id: _p, actor, event, ...rest } = e;
        return <tr key={e.id} className="static"><td>{dt(at)}</td><td>{actor}</td><td>{EVENTS[event] ?? event}</td>
          <td style={{ fontSize: 12 }}>{Object.entries(rest).filter(([, v]) => v !== null && v !== undefined && v !== '').map(([k2, v]) => `${k2} : ${fr(String(v))}`).join(' · ')}</td></tr>;
      })}</tbody></table></div>
  );
}
