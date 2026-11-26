import { createContext, useContext, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import { ApiError, metaOf, mlops, type ItemFilters, type ModelStatus, type ReadOpts, type RunSummary } from '../../api/mlops';
import { translate } from './messages';
import { combineMeta, ResourceStore, type CacheKind, type Loader } from './store';

/* Une seule source de données pour tout l'espace AI Leader (voir store.ts) :
   chaque ressource est chargée UNE fois, à la demande de la section qui l'affiche,
   et partagée. Aucune donnée de repli : une erreur reste une erreur. */

export const errText = (e: unknown) => (e instanceof ApiError ? `${e.status || 'réseau'} · ${translate(e.message)}` : translate(String(e)));

const Ctx = createContext<ResourceStore | null>(null);

export function MlopsDataProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => new ResourceStore({ timeoutMs: 30_000, errText }));
  return <Ctx.Provider value={store}>{children}</Ctx.Provider>;
}

export function useStore(): ResourceStore {
  const store = useContext(Ctx);
  if (!store) throw new Error('MlopsDataProvider manquant');
  return store;
}

/** Re-render on every store change (small app: simpler than per-key subscriptions). */
function useStoreVersion(store: ResourceStore) {
  return useSyncExternalStore(store.subscribe, store.getVersion);
}

export interface Resource<T> {
  data: T | null;
  /** Error with NO data to show. */
  error: string | null;
  loading: boolean;
  /** Last valid data shown while a new read runs. */
  refreshing: boolean;
  /** The last read failed: `data` is the last known value. */
  staleError: string | null;
  fetchedAt: string | null;
  cache: CacheKind;
}

const NONE: Resource<never> = { data: null, error: null, loading: false, refreshing: false, staleError: null, fetchedAt: null, cache: null };

/** Wraps an API read into a store loader carrying the response freshness. */
const read = <T,>(fn: (o: ReadOpts) => Promise<T>): Loader<T> =>
  (o) => fn(o).then((data) => ({ data, meta: metaOf(data) }));

/** Shared resource; `key` null = nothing to load (missing dependency). */
export function useResource<T>(key: string | null, loader: Loader<T>): Resource<T> {
  const store = useStore();
  useStoreVersion(store);
  const latest = useRef(loader);
  latest.current = loader;
  useEffect(() => (key ? store.mount<T>(key, (o) => latest.current(o)) : undefined), [key, store]);
  if (!key) return NONE;
  const s = store.snapshot<T>(key);
  const hasData = s.data !== undefined;
  return {
    data: hasData ? (s.data as T) : null,
    error: !hasData && s.status === 'error' ? s.error ?? 'erreur' : null,
    loading: !hasData && (s.status === 'idle' || s.status === 'loading'),
    refreshing: s.refreshing,
    staleError: hasData ? s.error ?? null : null,
    fetchedAt: s.fetchedAt ?? null,
    cache: s.cache ?? null,
  };
}

/* ------------------------------------------------------------------ ressources nommées */

export const useHealth = () => useResource('health', read(mlops.health));
export const useOverview = () => useResource('overview', read(mlops.overview));
export const useManaged = () => useResource('models', read(mlops.models));

/** Registry status of EVERY managed model; independent from the model list display. */
export function useStatuses(): Resource<ModelStatus[]> {
  const managed = useManaged();
  const ids = managed.data?.map((m) => m.id) ?? null;
  const resource = useResource<ModelStatus[]>(ids ? `statuses:${ids.join(',')}` : null, (o) =>
    Promise.all((ids ?? []).map((id) => mlops.status(id, o))).then((data) => ({ data, meta: combineMeta(data.map(metaOf)) })));
  if (managed.error) return { ...NONE, error: managed.error };
  return { ...resource, loading: resource.loading || managed.loading };
}

export const useCatalogs = () => useResource('catalogs', read(mlops.catalogs));
export const useSchemas = (catalog: string | null) =>
  useResource(catalog ? `schemas:${catalog}` : null, read((o) => mlops.schemas(catalog as string, o)));
export const useRun = (runId: string | null) =>
  useResource(runId ? `run:${runId}` : null, read((o) => mlops.run(runId as string, o)));

/** Several runs at once, from the SAME cache entries as useRun (one hook, no extra request). */
export function useRunMap(runIds: string[]): Resource<Record<string, RunSummary>> {
  const store = useStore();
  useStoreVersion(store);
  const joined = runIds.join(',');
  useEffect(() => {
    const unmount = runIds.map((id) => store.mount<RunSummary>(`run:${id}`, read((o) => mlops.run(id, o))));
    return () => unmount.forEach((u) => u());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [joined, store]);
  const snaps = runIds.map((id) => [id, store.snapshot<RunSummary>(`run:${id}`)] as const);
  const failed = snaps.find(([, s]) => s.data === undefined && s.status === 'error');
  if (failed) return { ...NONE, error: failed[1].error ?? 'erreur' };
  if (snaps.some(([, s]) => s.data === undefined)) return { ...NONE, loading: true };
  const meta = combineMeta(snaps.map(([, s]) => ({ fetchedAt: s.fetchedAt ?? null, cache: s.cache ?? null })));
  return {
    ...NONE,
    data: Object.fromEntries(snaps.map(([id, s]) => [id, s.data as RunSummary])),
    refreshing: snaps.some(([, s]) => s.refreshing),
    fetchedAt: meta.fetchedAt,
    cache: meta.cache,
  };
}

export const useExperiments = () => useResource('experiments', read(mlops.experiments));
export const useRuns = (experimentId: string | null) =>
  useResource(experimentId ? `runs:${experimentId}` : null, read((o) => mlops.runs(experimentId as string, o)));
export const useJobs = () => useResource('jobs', read(mlops.jobs));
export const useJobRuns = (jobId: number | null) =>
  useResource(jobId != null ? `jobruns:${jobId}` : null, read((o) => mlops.jobRuns(jobId as number, o)));
export const useEndpoints = () => useResource('endpoints', read(mlops.endpoints));
export const useMonitoring = (id: string | null) =>
  useResource(id ? `monitoring:${id}` : null, read((o) => mlops.monitoring(id as string, false, o)));

/** Freshness of what the current screen displays (not of the whole page). */
export function useFreshness() {
  const store = useStore();
  useStoreVersion(store);
  return store.summary();
}

/* ------------------------------------------------------------------ datasets (DBX-04) */

export const useDatasets = (modelId: string | null) =>
  useResource(modelId ? `datasets:${modelId}` : null, read((o) => mlops.datasets(modelId as string, o)));
export const useDatasetItems = (modelId: string | null, version: string | null, f: ItemFilters) =>
  useResource(
    modelId && version ? `dsitems:${modelId}:${version}:${JSON.stringify(f)}` : null,
    read((o) => mlops.datasetItems(modelId as string, version as string, f, o)),
  );
export const useDatasetTables = (modelId: string | null) =>
  useResource(modelId ? `dstables:${modelId}` : null, read((o) => mlops.datasetTables(modelId as string, o)));
export const useTrainingDataset = (modelId: string | null) =>
  useResource(modelId ? `trainingdataset:${modelId}` : null, read((o) => mlops.trainingDataset(modelId as string, o)));
export const useDraft = (modelId: string | null, draftId: string | null) =>
  useResource(modelId && draftId ? `draft:${modelId}:${draftId}` : null, read((o) => mlops.draft(modelId as string, draftId as string, o)));
