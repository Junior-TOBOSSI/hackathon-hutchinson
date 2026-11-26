import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { ApiError, mlops, type ModelStatus, type RunSummary } from '../../api/mlops';

/* Une seule source de données pour tout l'espace AI Leader :
   chaque ressource est chargée UNE fois (clé unique) et partagée entre les sections.
   « Actualiser » vide le cache. Aucune donnée de repli : une erreur reste une erreur. */

type Entry = { status: 'loading' | 'ok' | 'error'; data?: unknown; error?: string };

interface Store {
  get: (key: string, loader: () => Promise<unknown>) => Entry;
  refresh: () => void;
  invalidate: (...prefixes: string[]) => void;
  version: number;
  tick: number;
}

const Ctx = createContext<Store | null>(null);

export const errText = (e: unknown) => (e instanceof ApiError ? `${e.status || 'réseau'} · ${e.message}` : String(e));

export function MlopsDataProvider({ children }: { children: ReactNode }) {
  const [cache] = useState(() => new Map<string, Entry>());
  const [version, setVersion] = useState(0);
  const [tick, setTick] = useState(0);

  const get = useCallback((key: string, loader: () => Promise<unknown>) => {
    const existing = cache.get(key);
    if (existing) return existing;
    const entry: Entry = { status: 'loading' };
    cache.set(key, entry);
    loader()
      .then((data) => cache.set(key, { status: 'ok', data }))
      .catch((e) => cache.set(key, { status: 'error', error: errText(e) }))
      .finally(() => setTick((t) => t + 1));
    return entry;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  const refresh = useCallback(() => {
    cache.clear();
    setVersion((v) => v + 1);
  }, [cache]);

  /** Reload only the resources whose key starts with one of the prefixes. */
  const invalidate = useCallback((...prefixes: string[]) => {
    for (const key of [...cache.keys()]) if (prefixes.some((p) => key.startsWith(p))) cache.delete(key);
    setTick((t) => t + 1);
  }, [cache]);

  // tick change = a resource finished loading -> consumers re-render.
  const value = useMemo(() => ({ get, refresh, invalidate, version, tick }), [get, refresh, invalidate, version, tick]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore(): Store {
  const store = useContext(Ctx);
  if (!store) throw new Error('MlopsDataProvider manquant');
  return store;
}

export interface Resource<T> { data: T | null; error: string | null; loading: boolean }

/** Ressource partagée ; ``key`` null = ne rien charger (dépendance absente). */
export function useResource<T>(key: string | null, loader: () => Promise<T>): Resource<T> {
  const store = useStore();
  if (!key) return { data: null, error: null, loading: false };
  const entry = store.get(key, loader);
  return {
    data: entry.status === 'ok' ? (entry.data as T) : null,
    error: entry.status === 'error' ? entry.error ?? 'erreur' : null,
    loading: entry.status === 'loading',
  };
}

/* ------------------------------------------------------------------ ressources nommées */

export const useHealth = () => useResource('health', mlops.health);
export const useOverview = () => useResource('overview', mlops.overview);
export const useManaged = () => useResource('models', mlops.models);
/** Registry status of EVERY managed model, loaded once and shared by all sections. */
export function useStatuses(): Resource<ModelStatus[]> {
  const managed = useManaged();
  const ids = managed.data?.map((m) => m.id) ?? null;
  const resource = useResource(ids ? `statuses:${ids.join(',')}` : null, () => Promise.all((ids ?? []).map((id) => mlops.status(id))));
  if (managed.error) return { data: null, error: managed.error, loading: false };
  return { ...resource, loading: resource.loading || managed.loading };
}
export const useCatalogs = () => useResource('catalogs', mlops.catalogs);
export const useSchemas = (catalog: string | null) =>
  useResource(catalog ? `schemas:${catalog}` : null, () => mlops.schemas(catalog as string));
export const useRun = (runId: string | null) => useResource(runId ? `run:${runId}` : null, () => mlops.run(runId as string));

/** Several runs at once, from the SAME cache entries as useRun (one hook, no extra request). */
export function useRunMap(runIds: string[]): Resource<Record<string, RunSummary>> {
  const store = useStore();
  const entries = runIds.map((id) => [id, store.get(`run:${id}`, () => mlops.run(id))] as const);
  const failed = entries.find(([, e]) => e.status === 'error');
  if (failed) return { data: null, error: failed[1].error ?? 'erreur', loading: false };
  if (entries.some(([, e]) => e.status === 'loading')) return { data: null, error: null, loading: true };
  return { data: Object.fromEntries(entries.map(([id, e]) => [id, e.data as RunSummary])), error: null, loading: false };
}
export const useExperiments = () => useResource('experiments', mlops.experiments);
export const useRuns = (experimentId: string | null) =>
  useResource(experimentId ? `runs:${experimentId}` : null, () => mlops.runs(experimentId as string));
export const useJobs = () => useResource('jobs', mlops.jobs);
export const useJobRuns = (jobId: number | null) =>
  useResource(jobId != null ? `jobruns:${jobId}` : null, () => mlops.jobRuns(jobId as number));
export const useEndpoints = () => useResource('endpoints', mlops.endpoints);
export const useMonitoring = (id: string | null) =>
  useResource(id ? `monitoring:${id}` : null, () => mlops.monitoring(id as string));
