import { useSearchParams } from 'react-router-dom';
import { training, type RunStatus } from '../../../api/training';
import { read, useResource } from '../data';
import { Chip } from '../ui';

/* Ressources et utilitaires partagés de Training Factory (store DBX-PERF-01). */

export const useTrainingRuns = () => useResource('training:runs', read(training.runs));
export const useTrainingSummary = () => useResource('training:summary', read(training.summary));
export const usePipelines = () => useResource('training:pipelines', read(training.pipelines));
export const useCompatible = (pipelineId: string | null) =>
  useResource(pipelineId ? `training:compat:${pipelineId}` : null, read((o) => training.datasets(pipelineId as string, o)));
export const usePreview = (datasetId: string | null, version: string | null) =>
  useResource(datasetId && version ? `training:preview:${datasetId}:${version}` : null, read((o) => training.preview(datasetId as string, version as string, o)));
export const useRunDetail = (id: number | null) => useResource(id != null ? `training:run:${id}` : null, read((o) => training.run(id as number, o)));
export const useHistory = (runId: string | null) => useResource(runId ? `training:hist:${runId}` : null, read((o) => training.history(runId as string, o)));
export const useEvaluation = (runId: string | null) => useResource(runId ? `training:eval:${runId}` : null, read((o) => training.evaluation(runId as string, o)));
export const useArtifacts = (runId: string | null) => useResource(runId ? `training:art:${runId}` : null, read((o) => training.artifacts(runId as string, o)));
export const useLogs = (id: number | null) => useResource(id != null ? `training:logs:${id}` : null, read((o) => training.logs(id as number, o)));

const STATUS: Record<RunStatus, [string, 'green' | 'blue' | 'red' | 'grey' | 'amber']> = {
  succeeded: ['Terminé', 'green'], running: ['En cours', 'blue'], queued: ['En attente', 'blue'], failed: ['Échec', 'red'],
  cancelled: ['Annulé', 'grey'], unknown: ['Inconnu', 'amber'],
};
export const StatusChip = ({ status }: { status: RunStatus }) => <Chip tone={STATUS[status][1]}>{STATUS[status][0]}</Chip>;
export const statusLabel = (s: RunStatus) => STATUS[s][0];

export const duration = (s: number | null | undefined) => {
  if (s == null) return '—';
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.round(s % 60);
  return [h, m, sec].map((n) => String(n).padStart(2, '0')).join(':');
};
export const dt = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '—');

/** URL state of the section: ?section=training&run=<job run> | &new=1&pipeline=&dataset=&dsversion= */
export function useTfParams() {
  const [params, setParams] = useSearchParams();
  const set = (patch: Record<string, string | null>, reset = false) => {
    const next = reset ? new URLSearchParams({ section: 'training' }) : new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) if (v) next.set(k, v); else next.delete(k);
    setParams(next);
  };
  const run = params.get('run');
  return {
    run: run ? Number(run) : null, isNew: params.get('new') === '1', pipeline: params.get('pipeline'), dataset: params.get('dataset'),
    dsversion: params.get('dsversion'), prefill: params.get('params'), tab: params.get('tab'), set,
  };
}

export const pct = (v: number | null | undefined, digits = 1) => (v == null ? '—' : `${(v * 100).toFixed(digits).replace('.', ',')} %`);
export const num = (v: unknown) => (typeof v === 'number' ? v : typeof v === 'string' && v !== '' && !Number.isNaN(Number(v)) ? Number(v) : null);
