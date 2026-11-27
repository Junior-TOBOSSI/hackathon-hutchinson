// DBX-PERF-01 — store de l'espace AI Leader. Lancer : node --test argos-ui/tests/ai-leader-store.test.ts
// (Node >= 23 exécute le TypeScript directement ; aucune dépendance ajoutée.)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { combineMeta, ResourceStore, type LoadOptions, type Meta } from '../src/pages/ai-leader/store.ts';

const META: Meta = { fetchedAt: '2026-11-26T10:00:00+00:00', cache: 'miss' };
const tick = () => new Promise((r) => setTimeout(r, 0));

/** Loader whose answers are released manually, in any order. */
function controlled<T>() {
  const pending: { resolve: (v: T) => void; reject: (e: unknown) => void; options: LoadOptions }[] = [];
  const loader = (options: LoadOptions) =>
    new Promise<{ data: T; meta: Meta }>((resolve, reject) => {
      pending.push({ resolve: (v) => resolve({ data: v, meta: META }), reject, options });
    });
  return { loader, pending };
}

test('a late answer never overwrites a newer one (out of order)', async () => {
  const store = new ResourceStore({ timeoutMs: 500 });
  const { loader, pending } = controlled<string>();
  store.mount('k', loader);
  store.invalidate('k'); // second read (fresh) while the first is running
  assert.equal(pending.length, 2);
  assert.equal(pending[1].options.fresh, true);
  pending[1].resolve('new');
  await tick();
  pending[0].resolve('old');
  await tick();
  assert.equal(store.snapshot('k').data, 'new');
});

test('last valid data stays displayed while refreshing, then is replaced', async () => {
  const store = new ResourceStore({ timeoutMs: 500 });
  const { loader, pending } = controlled<string>();
  store.mount('k', loader);
  pending[0].resolve('v1');
  await tick();
  store.refresh();
  assert.equal(store.snapshot('k').data, 'v1');
  assert.equal(store.snapshot('k').refreshing, true);
  pending[1].resolve('v2');
  await tick();
  assert.deepEqual([store.snapshot('k').data, store.snapshot('k').refreshing], ['v2', false]);
});

test('an error never replaces valid data; it is reported next to it', async () => {
  const store = new ResourceStore({ timeoutMs: 500, errText: (e) => String((e as Error).message) });
  const { loader, pending } = controlled<string>();
  store.mount('k', loader);
  pending[0].resolve('valid');
  await tick();
  store.refresh();
  pending[1].reject(new Error('503 Databricks unreachable'));
  await tick();
  const s = store.snapshot('k');
  assert.equal(s.data, 'valid');
  assert.equal(s.error, '503 Databricks unreachable');
  assert.equal(s.status, 'ok');
});

test('a request that never answers ends in an explicit timeout (no endless spinner)', async () => {
  const store = new ResourceStore({ timeoutMs: 20 });
  store.mount('k', ({ signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')))));
  await new Promise((r) => setTimeout(r, 60));
  const s = store.snapshot('k');
  assert.equal(s.status, 'error');
  assert.match(s.error ?? '', /Délai dépassé/);
});

test('refresh re-reads displayed resources only; hidden ones on their next display', async () => {
  const store = new ResourceStore({ timeoutMs: 500 });
  const a = controlled<string>();
  const b = controlled<string>();
  store.mount('shown', a.loader);
  const unmount = store.mount('hidden', b.loader);
  a.pending[0].resolve('a');
  b.pending[0].resolve('b');
  await tick();
  unmount();
  store.refresh();
  assert.equal(a.pending.length, 2);
  assert.equal(b.pending.length, 1); // not re-read while hidden
  store.mount('hidden', b.loader);
  assert.equal(b.pending.length, 2);
  assert.equal(b.pending[1].options.fresh, true);
});

test('repeated refresh clicks do not multiply requests', async () => {
  const store = new ResourceStore({ timeoutMs: 500 });
  const { loader, pending } = controlled<string>();
  store.mount('k', loader);
  pending[0].resolve('v');
  await tick();
  store.refresh();
  store.refresh();
  store.refresh();
  assert.equal(pending.length, 2);
});

test('one failing resource does not affect the others', async () => {
  const store = new ResourceStore({ timeoutMs: 500 });
  const ok = controlled<string>();
  const ko = controlled<string>();
  store.mount('ok', ok.loader);
  store.mount('ko', ko.loader);
  ko.pending[0].reject(new Error('boom'));
  ok.pending[0].resolve('fine');
  await tick();
  assert.equal(store.snapshot('ok').data, 'fine');
  assert.equal(store.snapshot('ko').status, 'error');
});

test('model change = another key; returning to a failed resource retries it', async () => {
  const store = new ResourceStore({ timeoutMs: 500 });
  const { loader, pending } = controlled<string>();
  const off = store.mount('status:a', loader);
  pending[0].reject(new Error('timeout'));
  await tick();
  off();
  store.mount('status:b', loader);
  assert.equal(pending.length, 2);
  store.mount('status:a', loader);
  assert.equal(pending.length, 3);
});

test('summary reports the real read range, not a single page date', async () => {
  const store = new ResourceStore({ timeoutMs: 500 });
  store.mount('x', async () => ({ data: 1, meta: { fetchedAt: '2026-11-26T10:00:00+00:00', cache: 'hit' } }));
  store.mount('y', async () => ({ data: 2, meta: { fetchedAt: '2026-11-26T10:05:00+00:00', cache: 'miss' } }));
  await tick();
  const s = store.summary();
  assert.equal(s.oldest, '2026-11-26T10:00:00+00:00');
  assert.equal(s.newest, '2026-11-26T10:05:00+00:00');
  assert.deepEqual(s.kinds.sort(), ['hit', 'miss']);
  assert.equal(s.loading, 0);
});

test('combined freshness keeps the oldest read and flags stale data', () => {
  const m = combineMeta([
    { fetchedAt: '2026-11-26T10:05:00+00:00', cache: 'miss' },
    { fetchedAt: '2026-11-26T10:00:00+00:00', cache: 'stale' },
  ]);
  assert.deepEqual(m, { fetchedAt: '2026-11-26T10:00:00+00:00', cache: 'stale' });
});
