// DBX-09 targeted frontend tests: `node --test src/pages/ai-leader/overview/history.test.ts`
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { bucketRuns, frReason, groupOf, type RunLike } from './history.ts';

const NOW = new Date('2026-11-27T12:00:00').getTime();
const run = (status: RunLike['status'], started_at: string | null): RunLike => ({ status, started_at });

test('every status belongs to exactly one group', () => {
  assert.equal(groupOf('succeeded'), 'Réussis');
  assert.equal(groupOf('failed'), 'Échoués');
  assert.equal(groupOf('queued'), 'En cours');
  assert.equal(groupOf('running'), 'En cours');
  assert.equal(groupOf('cancelled'), 'Annulés / inconnus');
  assert.equal(groupOf('unknown'), 'Annulés / inconnus');
});

test('real runs are grouped by day with their statuses, nothing is invented', () => {
  const runs = [run('succeeded', '2026-11-26T10:00:00'), run('failed', '2026-11-26T11:00:00'),
    run('running', '2026-11-27T09:00:00'), run('succeeded', null)];
  const { buckets, runs: kept, weekly } = bucketRuns(runs, '30', NOW);
  assert.equal(weekly, false);
  assert.equal(kept.length, 3); // the run without a start date is not placed on the axis
  assert.deepEqual(buckets, [['2026-11-26', { Réussis: 1, Échoués: 1 }], ['2026-11-27', { 'En cours': 1 }]]);
});

test('the period filter drops older runs and long periods are grouped by week', () => {
  const runs = [run('succeeded', '2026-08-01T10:00:00'), run('failed', '2026-11-25T10:00:00'), run('failed', '2026-11-26T10:00:00')];
  assert.equal(bucketRuns(runs, '14', NOW).runs.length, 2);
  const all = bucketRuns(runs, 'all', NOW);
  assert.equal(all.weekly, true);
  assert.deepEqual(all.buckets.map(([k]) => k), ['2026-07-27', '2026-11-23']);
  assert.deepEqual(all.buckets[1][1], { Échoués: 2 });
});

test('no run gives no bucket', () => {
  assert.deepEqual(bucketRuns([], '30', NOW).buckets, []);
});

test('known backend reasons are shown in French, unknown ones unchanged', () => {
  assert.equal(frReason('1 manual request(s) by ai_leader'), '1 demande(s) manuelle(s) de ai_leader');
  assert.equal(frReason('something else'), 'something else');
  assert.equal(frReason(null), null);
});
