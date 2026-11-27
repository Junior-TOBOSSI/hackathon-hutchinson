import type { ManagedModel, ModelStatus } from '../../api/mlops';
import { useNav } from './common';
import { useManaged, useStatuses } from './data';

/** Emplacements des modèles des trois groupes IA : affichés, jamais simulés. */
export const PENDING_SLOTS = [
  { name: 'Quality Inspection', group: 'Groupe Quality', useCase: 'Qualité' },
  { name: 'PPE Detection', group: 'Groupe PPE', useCase: 'EPI' },
  { name: 'Behavior Detection', group: 'Groupe Behavior', useCase: 'Comportement' },
];

export interface Selection {
  models: ManagedModel[];
  model: ManagedModel | null;
  status: ModelStatus | null;
  /** Model list only (configuration, ~30 ms): never waits for the registry status. */
  loading: boolean;
  error: string | null;
  /** Registry status of the selected model, loaded independently. */
  statusLoading: boolean;
  statusError: string | null;
}

/** Modèle courant = ?model=… s'il existe, sinon le premier modèle géré. */
export function useSelection(): Selection {
  const { model: wanted } = useNav();
  const managed = useManaged();
  const statuses = useStatuses();
  const models = managed.data ?? [];
  const model = models.find((m) => m.id === wanted) ?? models[0] ?? null;
  const status = statuses.data?.find((s) => s.model_id === model?.id) ?? null;
  return {
    models,
    model,
    status,
    loading: managed.loading,
    error: managed.error,
    statusLoading: statuses.loading,
    statusError: statuses.error,
  };
}

/** Version servie (premier endpoint du modèle), champion, et cohérence des trois notions. */
export function versionRoles(status: ModelStatus | null) {
  const served = status ? Object.values(status.served).find((v) => v) ?? null : null;
  const champion = status?.aliases.champion ?? null;
  const approved = status?.versions.filter((v) => v.approved).map((v) => v.version.version) ?? [];
  return { served, champion, approved, championApproved: champion ? approved.includes(champion) : null };
}
