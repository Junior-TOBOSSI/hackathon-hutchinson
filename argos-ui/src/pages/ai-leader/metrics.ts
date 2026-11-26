/* Lecture générique des métriques MLflow, quel que soit le modèle (classification,
   détection, autre). Règles : on n'affiche QUE ce qui existe ; une clé inconnue garde
   son nom technique ; aucune valeur n'est calculée ou inventée côté interface. */

export type Split = 'validation' | 'test' | 'production' | 'human' | 'training' | 'other';

export const SPLIT_LABEL: Record<Split, string> = {
  validation: 'Validation (hors ligne)',
  test: 'Test (hors ligne)',
  production: 'Production (mesuré en ligne)',
  human: 'Accord avec les annotations humaines',
  training: 'Entraînement',
  other: 'Autres mesures',
};

const SPLIT_PREFIXES: [string, Split][] = [
  ['validation_', 'validation'], ['val_', 'validation'],
  ['test_', 'test'],
  ['production_', 'production'], ['prod_', 'production'],
  ['human_', 'human'], ['agreement_', 'human'],
  ['train_', 'training'], ['training_', 'training'],
];

const BASE_LABEL: Record<string, string> = {
  accuracy: 'Exactitude', precision: 'Précision', recall: 'Rappel', f1: 'F1', f1_score: 'F1',
  auc: 'AUC', roc_auc: 'AUC ROC', pr_auc: 'AUC PR', map: 'mAP', map50: 'mAP@50', map50_95: 'mAP@50-95',
  iou: 'IoU', loss: 'Perte', log_loss: 'Perte logistique', false_reject_rate: 'Taux de faux rejets',
  false_accept_rate: 'Taux de faux acceptés', time_s: 'Durée', latency_ms: 'Latence', latency_ms_p95: 'Latence p95',
};

// Bases mesurées dans [0, 1] et affichées en pourcentage.
const RATIO = new Set(['accuracy', 'precision', 'recall', 'f1', 'f1_score', 'auc', 'roc_auc', 'pr_auc', 'map', 'map50',
  'map50_95', 'iou', 'false_reject_rate', 'false_accept_rate']);
// Sens favorable (pour les couleurs uniquement ; inconnu = neutre).
const LOWER_IS_BETTER = new Set(['loss', 'log_loss', 'false_reject_rate', 'false_accept_rate', 'time_s', 'latency_ms', 'latency_ms_p95']);

export interface MetricInfo {
  key: string;
  split: Split;
  base: string;
  qualifier: string | null;
  label: string;
  kind: 'ratio' | 'seconds' | 'milliseconds' | 'number';
  lowerIsBetter: boolean | null;
}

export function describe(key: string): MetricInfo {
  let split: Split = 'other';
  let rest = key;
  for (const [prefix, s] of SPLIT_PREFIXES) {
    if (key.startsWith(prefix)) { split = s; rest = key.slice(prefix.length); break; }
  }
  // Base = longest known label that prefixes the rest ; qualifier = remainder (class, macro…).
  const base = Object.keys(BASE_LABEL).sort((a, b) => b.length - a.length).find((b) => rest === b || rest.startsWith(`${b}_`)) ?? rest;
  const qualifierRaw = rest === base ? null : rest.slice(base.length + 1);
  const qualifier = qualifierRaw ? qualifierRaw.replace(/_/g, ' ').replace(/\bnok\b/i, 'NOK').replace(/\bok\b/i, 'OK') : null;
  const known = base in BASE_LABEL;
  const label = known ? `${BASE_LABEL[base]}${qualifier ? ` · ${qualifier}` : ''}` : key;
  const kind = RATIO.has(base) ? 'ratio'
    : /(^|_)ms(_|$)/.test(base) ? 'milliseconds'
      : /(^|_)s$/.test(base) ? 'seconds' : 'number';
  return { key, split, base, qualifier, label, kind, lowerIsBetter: known ? LOWER_IS_BETTER.has(base) : null };
}

export function format(info: MetricInfo, value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  switch (info.kind) {
    case 'ratio': return `${(value * 100).toFixed(1).replace('.', ',')} %`;
    case 'seconds': return value < 60 ? `${value.toFixed(value < 1 ? 2 : 1).replace('.', ',')} s` : `${(value / 60).toFixed(1).replace('.', ',')} min`;
    case 'milliseconds': return `${Math.round(value)} ms`;
    default: return Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(3).replace('.', ',');
  }
}

/** Groupe les métriques d'un run par split, dans un ordre stable (validation, test…). */
export function groupBySplit(metrics: Record<string, number>): { split: Split; items: { info: MetricInfo; value: number }[] }[] {
  const order: Split[] = ['validation', 'test', 'production', 'human', 'training', 'other'];
  const groups = new Map<Split, { info: MetricInfo; value: number }[]>();
  for (const [key, value] of Object.entries(metrics)) {
    const info = describe(key);
    groups.set(info.split, [...(groups.get(info.split) ?? []), { info, value }]);
  }
  return order.filter((s) => groups.has(s)).map((split) => ({
    split, items: (groups.get(split) ?? []).sort((a, b) => a.info.label.localeCompare(b.info.label, 'fr')),
  }));
}

export const pct = (value: number | null | undefined) =>
  value == null ? '—' : `${(value * 100).toFixed(1).replace('.', ',')} %`;

export const dateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '—';

export const duration = (start: string | null | undefined, end: string | null | undefined) => {
  if (!start || !end) return '—';
  const s = (new Date(end).getTime() - new Date(start).getTime()) / 1000;
  return s < 60 ? `${s.toFixed(1).replace('.', ',')} s` : `${(s / 60).toFixed(1).replace('.', ',')} min`;
};
