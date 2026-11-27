import type { ManagedModel, ModelStatus, RunSummary, VersionStatus } from '../../api/mlops';

export interface ModelRow {
  model: ManagedModel;
  status: ModelStatus | null;
  versions: number;
  latest: VersionStatus | null;
  champion: string | null;
  served: string | null;
  pending: number;
  activity: string | null;
  architecture: string | null;
}

const versionNumber = (version: string) => Number.parseInt(version, 10) || 0;
export const decisionOf = (version: VersionStatus) =>
  version.version.tags.argos_approval === 'approved' ? 'approved'
    : version.version.tags.argos_approval === 'rejected' ? 'rejected' : 'pending';

/** All counts are scoped to configured HOVIS models whose UC status was read successfully. */
export function modelCatalog(models: ManagedModel[], statuses: ModelStatus[]): ModelRow[] {
  return models.map((model) => {
    const status = statuses.find((item) => item.model_id === model.id) ?? null;
    const sorted = [...(status?.versions ?? [])].sort((a, b) =>
      versionNumber(b.version.version) - versionNumber(a.version.version));
    const latest = sorted[0] ?? null;
    return {
      model, status, versions: sorted.length, latest,
      champion: status?.aliases.champion ?? null,
      served: status ? Object.values(status.served).find(Boolean) ?? null : null,
      pending: sorted.filter((version) => decisionOf(version) === 'pending').length,
      activity: sorted.flatMap((version) => [version.version.created_at, version.version.tags.argos_decision_at])
        .filter((date): date is string => !!date)
        .sort().reverse()[0] ?? null,
      architecture: latest?.version.tags.argos_architecture ?? latest?.version.tags.architecture
        ?? latest?.version.tags.argos_task ?? latest?.version.tags.task ?? null,
    };
  });
}

export function modelCounts(rows: ModelRow[]) {
  const versions = rows.flatMap((row) => row.status?.versions ?? []);
  return {
    models: rows.filter((row) => row.status !== null).length,
    versions: versions.length,
    pending: versions.filter((version) => decisionOf(version) === 'pending').length,
    approved: versions.filter((version) => decisionOf(version) === 'approved').length,
    champions: rows.filter((row) => row.champion).length,
    served: versions.filter((version) => version.served_by.length > 0).length,
  };
}

export interface ComparableMetric { label: string; bases: string[]; unit: 'percent' | 'count' | 'ms' }
export const COMPARABLE_METRICS: ComparableMetric[] = [
  { label: 'Exactitude', bases: ['accuracy'], unit: 'percent' },
  { label: 'Précision', bases: ['precision'], unit: 'percent' },
  { label: 'Rappel', bases: ['recall'], unit: 'percent' },
  { label: 'F1-score', bases: ['f1_score', 'f1'], unit: 'percent' },
  { label: 'Taux de faux rejets', bases: ['false_reject_rate'], unit: 'percent' },
  { label: 'Faux rejets', bases: ['false_rejects', 'false_reject_count'], unit: 'count' },
  { label: 'Taux de défauts manqués', bases: ['missed_defects_rate', 'false_negative_rate'], unit: 'percent' },
  { label: 'Défauts manqués', bases: ['missed_defects', 'false_negative_count'], unit: 'count' },
  { label: 'Latence', bases: ['latency_ms_p95', 'latency_ms'], unit: 'ms' },
];

/** Include class-qualified keys (for example val_f1_nok) without assuming a particular class. */
export function comparableMetricRows(runs: RunSummary[], split: 'validation' | 'test'): ComparableMetric[] {
  const prefixes = split === 'validation' ? ['validation_', 'val_'] : ['test_'];
  const keys = [...new Set(runs.flatMap((run) => Object.keys(run.metrics)))];
  const rows: ComparableMetric[] = [];
  for (const metric of COMPARABLE_METRICS) {
    const qualifiers = new Set<string>();
    for (const key of keys) {
      const prefix = prefixes.find((item) => key.startsWith(item));
      if (!prefix) continue;
      const name = key.slice(prefix.length);
      const base = [...metric.bases].sort((a, b) => b.length - a.length)
        .find((item) => name === item || name.startsWith(`${item}_`));
      if (base) qualifiers.add(name.slice(base.length).replace(/^_/, ''));
    }
    for (const qualifier of [...qualifiers].sort()) {
      rows.push({ label: `${metric.label}${qualifier ? ` · ${qualifier.replace(/_/g, ' ')}` : ''}`,
        bases: metric.bases.map((base) => `${base}${qualifier ? `_${qualifier}` : ''}`), unit: metric.unit });
    }
  }
  return rows;
}

export function metricValue(run: RunSummary | null | undefined, split: 'validation' | 'test', bases: string[]): number | null {
  if (!run) return null;
  for (const prefix of split === 'validation' ? ['validation_', 'val_'] : ['test_']) {
    for (const base of bases) {
      const value = run.metrics[`${prefix}${base}`];
      if (value != null && Number.isFinite(value)) return value;
    }
  }
  return null;
}

/** Absence of protocol/split metadata means unknown comparability, never an assumed match. */
export function comparability(runs: RunSummary[]) {
  if (runs.length < 2) return 'Sélectionnez au moins deux versions avec un run.';
  const keys = ['dataset_version', 'evaluation_protocol', 'split_strategy', 'split_seed'];
  for (const key of keys) {
    const values = runs.map((run) => run.params[key]);
    if (new Set(values.filter(Boolean)).size > 1) return `Comparaison non fiable : ${key} diffère.`;
  }
  if (runs.some((run) => !run.params.dataset_version || !run.params.evaluation_protocol || !run.params.split_strategy)) {
    return 'Comparabilité non vérifiable : dataset, protocole ou découpage non renseigné.';
  }
  return 'Même dataset, protocole et stratégie de découpage déclarés dans MLflow.';
}

export function confusion(run: RunSummary | null | undefined, split: 'validation' | 'test') {
  const parts = ['tp', 'tn', 'fp', 'fn'].map((key) => metricValue(run, split, [key]));
  return parts.every((part) => part != null)
    ? { tp: parts[0] as number, tn: parts[1] as number, fp: parts[2] as number, fn: parts[3] as number }
    : null;
}
