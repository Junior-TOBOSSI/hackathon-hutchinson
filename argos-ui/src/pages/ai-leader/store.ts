/* Store des ressources de l'espace AI Leader (DBX-PERF-01), indépendant de React.

   - une clé = une ressource, chargée une seule fois et partagée par les sections ;
   - chaque chargement porte un numéro de génération : une réponse arrivée après une
     réponse plus récente (désordre, actualisation, invalidation) est ignorée ;
   - pendant une actualisation, la dernière donnée valide reste affichée (refreshing) ;
   - une erreur ne remplace jamais une donnée valide : elle est signalée à côté ;
   - délai d'expiration explicite : aucun indicateur de chargement ne peut rester bloqué ;
   - fetchedAt / cache = date réelle de lecture Databricks et origine, fournies par le backend.

   Écrit sans syntaxe TypeScript « non effaçable » (pas d'enum ni de propriété de paramètre)
   pour être testé directement avec `node --test`. */

export type CacheKind = 'hit' | 'miss' | 'mixed' | 'stale' | null;
export interface Meta { fetchedAt: string | null; cache: CacheKind }
export interface LoadOptions { fresh: boolean; signal: AbortSignal }
export type Loader<T> = (options: LoadOptions) => Promise<{ data: T; meta: Meta }>;

export interface Snapshot<T = unknown> {
  status: 'idle' | 'loading' | 'ok' | 'error';
  data?: T;
  error?: string;
  fetchedAt?: string | null;
  cache?: CacheKind;
  refreshing: boolean;
}

export interface Summary {
  mounted: number;
  loading: number;
  refreshing: number;
  errors: number;
  staleAfterError: number;
  oldest: string | null;
  newest: string | null;
  kinds: CacheKind[];
}

const IDLE: Snapshot = { status: 'idle', refreshing: false };

export interface StoreOptions { timeoutMs?: number; errText?: (e: unknown) => string }

export class ResourceStore {
  version = 0;
  readonly timeoutMs: number;
  private readonly errText: (e: unknown) => string;
  private entries = new Map<string, Snapshot>();
  private loaders = new Map<string, Loader<unknown>>();
  private generations = new Map<string, number>();
  private controllers = new Map<string, AbortController>();
  private mounted = new Map<string, number>();
  private stale = new Set<string>();
  private listeners = new Set<() => void>();

  constructor(options: StoreOptions = {}) {
    this.timeoutMs = options.timeoutMs ?? 30_000;
    this.errText = options.errText ?? ((e) => String(e));
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  getVersion = () => this.version;

  snapshot<T>(key: string): Snapshot<T> {
    return (this.entries.get(key) ?? IDLE) as Snapshot<T>;
  }

  /** A component displays `key`: load it if never loaded (or marked stale). */
  mount<T>(key: string, loader: Loader<T>): () => void {
    this.loaders.set(key, loader as Loader<unknown>);
    this.mounted.set(key, (this.mounted.get(key) ?? 0) + 1);
    const entry = this.entries.get(key);
    if (!entry || entry.status === 'idle' || entry.status === 'error') this.load(key, false);
    else if (this.stale.has(key) && !entry.refreshing) this.load(key, true);
    return () => {
      const n = (this.mounted.get(key) ?? 1) - 1;
      if (n <= 0) this.mounted.delete(key); else this.mounted.set(key, n);
    };
  }

  /** « Actualiser » : real re-read (fresh) of the DISPLAYED resources only; the others
      are re-read when their section opens. A resource already refreshing is not re-sent. */
  refresh(): void {
    this.reload(() => true);
  }

  /** After a mutation: re-read (fresh) the matching resources. */
  invalidate(...prefixes: string[]): void {
    this.reload((key) => prefixes.some((p) => key.startsWith(p)));
  }

  private reload(match: (key: string) => boolean): void {
    for (const key of [...this.entries.keys()]) {
      if (!match(key)) continue;
      if (this.mounted.has(key)) {
        if (!this.entries.get(key)?.refreshing) this.load(key, true);
      } else {
        this.stale.add(key);
      }
    }
  }

  summary(): Summary {
    const s: Summary = { mounted: 0, loading: 0, refreshing: 0, errors: 0, staleAfterError: 0, oldest: null, newest: null, kinds: [] };
    for (const key of this.mounted.keys()) {
      const e = this.entries.get(key);
      if (!e) continue;
      s.mounted += 1;
      if (e.status === 'loading' || e.status === 'idle') s.loading += 1;
      if (e.refreshing) s.refreshing += 1;
      if (e.status === 'error') s.errors += 1;
      if (e.status === 'ok' && e.error) s.staleAfterError += 1;
      if (e.fetchedAt) {
        if (!s.oldest || e.fetchedAt < s.oldest) s.oldest = e.fetchedAt;
        if (!s.newest || e.fetchedAt > s.newest) s.newest = e.fetchedAt;
      }
      if (e.cache && !s.kinds.includes(e.cache)) s.kinds.push(e.cache);
    }
    return s;
  }

  private emit(): void {
    this.version += 1;
    for (const listener of [...this.listeners]) listener();
  }

  private set(key: string, entry: Snapshot): void {
    this.entries.set(key, entry);
    this.emit();
  }

  private load(key: string, fresh: boolean): void {
    const loader = this.loaders.get(key);
    if (!loader) return;
    const generation = (this.generations.get(key) ?? 0) + 1;
    this.generations.set(key, generation);
    this.stale.delete(key);
    this.controllers.get(key)?.abort();
    const controller = new AbortController();
    this.controllers.set(key, controller);
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, this.timeoutMs);

    const previous = this.entries.get(key);
    const hasData = previous?.data !== undefined;
    this.set(key, hasData
      ? { ...(previous as Snapshot), refreshing: true }
      : { status: 'loading', refreshing: false });

    const current = () => this.generations.get(key) === generation;
    loader({ fresh, signal: controller.signal })
      .then(({ data, meta }) => {
        if (!current()) return; // a newer read exists: this answer is obsolete
        this.set(key, { status: 'ok', data, fetchedAt: meta.fetchedAt, cache: meta.cache, refreshing: false });
      })
      .catch((e: unknown) => {
        if (!current()) return;
        const message = timedOut
          ? `Délai dépassé (${Math.round(this.timeoutMs / 1000)} s) : Databricks ne répond pas`
          : this.errText(e);
        const last = this.entries.get(key);
        if (last?.data !== undefined) {
          // Keep the last valid value, flagged: never replaced by an error.
          this.set(key, { ...last, error: message, refreshing: false });
        } else {
          this.set(key, { status: 'error', error: message, refreshing: false });
        }
      })
      .finally(() => {
        clearTimeout(timer);
        if (this.controllers.get(key) === controller) this.controllers.delete(key);
      });
  }
}

/** Freshness of a response combining several reads (e.g. one status per model). */
export function combineMeta(metas: Meta[]): Meta {
  const dates = metas.map((m) => m.fetchedAt).filter((d): d is string => !!d).sort();
  const kinds = [...new Set(metas.map((m) => m.cache).filter((k): k is Exclude<CacheKind, null> => !!k))];
  const cache: CacheKind = kinds.includes('stale') ? 'stale' : kinds.length === 0 ? null : kinds.length === 1 ? kinds[0] : 'mixed';
  return { fetchedAt: dates[0] ?? null, cache };
}
