import { useCallback, useEffect, useState } from 'react';

/** Charge une donnée et la rafraîchit toutes les `refreshMs` ms (0 = pas de rafraîchissement). */
export function useApi<T>(load: () => Promise<T>, deps: unknown[] = [], refreshMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    load().then(setData).catch((e: Error) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    reload();
    if (!refreshMs) return;
    const t = setInterval(reload, refreshMs);
    return () => clearInterval(t);
  }, [reload, refreshMs]);

  return { data, error, reload, setData };
}
