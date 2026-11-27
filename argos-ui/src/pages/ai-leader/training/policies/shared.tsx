import { retraining, type ConditionKind, type ConditionState, type ProposalStatus } from '../../../../api/retraining';
import { read, useResource } from '../../data';
import { Chip } from '../../ui';

/* Politiques de réentraînement (DBX-08B) : ressources « ret: » du store DBX-PERF-01. */

export const useRetrainKpis = () => useResource('ret:kpis', read(retraining.kpis));
export const useRetrainOptions = () => useResource('ret:options', read(retraining.options));
export const usePolicies = () => useResource('ret:policies', read(retraining.policies));
export const usePolicy = (id: string | null) => useResource(id ? `ret:policy:${id}` : null, read((o) => retraining.policy(id as string, o)));
export const useEvaluations = (id: string | null) => useResource(id ? `ret:evals:${id}` : null, read((o) => retraining.evaluations(id as string, o)));
export const useProposals = () => useResource('ret:proposals', read(retraining.proposals));
export const useAudit = (id: string | null) => useResource(`ret:audit:${id ?? '*'}`, read((o) => retraining.audit(id, o)));

export const USE_CASES: [string, string][] = [['quality', 'Qualité'], ['safety', 'Sécurité (EPI)'], ['workstation', 'Poste de travail / 5S']];
export const useCaseFr = (u: string) => USE_CASES.find(([k]) => k === u)?.[1] ?? u;

export const CONDITION_LABEL: Record<ConditionKind, string> = {
  drift: 'Dérive persistante', annotations: 'Nouvelles annotations validées', performance: 'Dégradation de performances',
  schedule: 'Planification', manual: 'Demande manuelle',
};
const STATE: Record<ConditionState, [string, 'green' | 'grey' | 'amber']> = {
  satisfied: ['Satisfaite', 'green'], not_satisfied: ['Non satisfaite', 'grey'], unavailable: ['Indisponible', 'amber'],
};
export const StateChip = ({ state }: { state: ConditionState }) => <Chip tone={STATE[state][1]}>{STATE[state][0]}</Chip>;

const PROPOSAL: Record<ProposalStatus, [string, 'green' | 'grey' | 'amber' | 'blue' | 'red']> = {
  pending: ['En attente', 'amber'], accepted: ['Acceptée', 'blue'], launching: ['Lancement…', 'blue'], launched: ['Lancée', 'green'],
  uncertain: ['Réponse incertaine', 'red'], rejected: ['Refusée', 'grey'],
};
export const ProposalChip = ({ status }: { status: ProposalStatus }) => <Chip tone={PROPOSAL[status][1]}>{PROPOSAL[status][0]}</Chip>;

export const GUARD_LABEL: Record<string, string> = {
  remote_lock: 'Verrou distant', allowed_hours: 'Plage horaire', cpu_only: 'CPU uniquement', no_concurrent_training: 'Aucun entraînement concurrent',
  code_version: 'Version du code scientifique', real_data_only: 'Preuves réelles uniquement', monthly_budget: 'Budget mensuel', min_delay: 'Délai minimal',
};

const REASONS: [RegExp, string][] = [
  [/^no active condition: this policy never triggers$/, 'aucune condition active : cette politique ne déclenche jamais'],
  [/^OR: no active condition is satisfied$/, 'OU : aucune condition active n’est satisfaite'],
  [/^AND: every active condition is satisfied$/, 'ET : toutes les conditions actives sont satisfaites'],
  [/no previous successful training of this pipeline on this dataset family: no baseline to count new annotations/, 'aucun entraînement réussi de ce pipeline sur cette famille : pas de base pour compter les nouvelles annotations'],
  [/no representative labelled production sample \(ground truth\): production performance cannot be measured/, 'aucun échantillon de production étiqueté représentatif : la performance en production n’est pas mesurable'],
  [/no inference is linked to this registered model by an exact package reference: its drift cannot be evaluated/, 'aucune inférence n’est reliée à ce modèle du registre par une référence exacte de paquet : dérive non évaluable'],
  [/no pending manual request/, 'aucune demande manuelle en attente'],
  [/remote launches not authorized/, 'lancements distants non autorisés (HOVIS_TRAINING_REMOTE)'],
];
/** French rendering of the backend reasons (unknown texts are shown as they are). */
export const fr = (text: string) => REASONS.reduce((t, [re, rep]) => t.replace(re, rep), text);
