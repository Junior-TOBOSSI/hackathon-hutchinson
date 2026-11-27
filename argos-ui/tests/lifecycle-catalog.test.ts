import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ManagedModel, ModelStatus, RunSummary } from '../src/api/mlops.ts';
import { comparableMetricRows, comparability, confusion, decisionOf, metricValue, modelCatalog, modelCounts } from '../src/pages/ai-leader/lifecycleCatalog.ts';

const model = { id: 'candidate-A', display_name: 'Candidat A', uc_name: 'catalog.schema.candidate_a', argos_use_case: 'quality' } as ManagedModel;
const version = (number: string, approval?: string) => ({
  version: { version: number, created_at: `2026-11-2${number}T09:00:00Z`,
    tags: approval ? { argos_approval: approval } : {}, run_id: `run-${number}` },
  approved: approval === 'approved', aliases: number === '2' ? ['champion'] : [],
  served_by: number === '1' ? ['endpoint-A'] : [],
});
const status = { model_id: model.id, aliases: { champion: '2' }, served: { 'endpoint-A': '1' },
  versions: [version('1', 'approved'), version('2', 'rejected'), version('3')] } as ModelStatus;
const run = (params: Record<string, string>, metrics: Record<string, number>) => ({ params, metrics }) as RunSummary;

test('catalogue et KPI utilisent seulement les statuts gérés réellement reçus', () => {
  const rows = modelCatalog([model], [status]);
  assert.equal(rows[0].latest?.version.version, '3');
  assert.equal(rows[0].champion, '2');
  assert.equal(rows[0].served, '1');
  assert.equal(decisionOf(status.versions[2]), 'pending');
  assert.deepEqual(modelCounts(rows), { models: 1, versions: 3, pending: 1, approved: 1, champions: 1, served: 1 });
  assert.equal(modelCounts(modelCatalog([model], [])).models, 0);
});

test('comparaison signale les métadonnées manquantes ou différentes', () => {
  const a = run({ dataset_version: 'v1', evaluation_protocol: 'fixed', split_strategy: 'by_station' }, {});
  const b = run({ dataset_version: 'v2', evaluation_protocol: 'fixed', split_strategy: 'by_station' }, {});
  assert.match(comparability([a, b]), /diffère/);
  assert.match(comparability([a, run({}, {})]), /non vérifiable/);
  assert.match(comparability([a, run({ dataset_version: 'v1' }, {})]), /non vérifiable/);
  assert.match(comparability([a, a]), /^Même dataset/);
});

test('métriques et matrice ne sont affichées que si les valeurs existent', () => {
  const result = run({}, { val_accuracy: 0.91, val_f1_nok: 0.85, val_tp: 12, val_tn: 30, val_fp: 2, val_fn: 1 });
  assert.equal(metricValue(result, 'validation', ['accuracy']), 0.91);
  const f1 = comparableMetricRows([result], 'validation').find((item) => item.label === 'F1-score · nok');
  assert.equal(metricValue(result, 'validation', f1?.bases ?? []), 0.85);
  assert.equal(metricValue(result, 'test', ['accuracy']), null);
  assert.deepEqual(confusion(result, 'validation'), { tp: 12, tn: 30, fp: 2, fn: 1 });
  assert.equal(confusion(result, 'test'), null);
});
