import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { EdgeStation } from '../src/api/deployment.ts';
import { filterStations, modelState, modelText, rawModelText } from '../src/pages/ai-leader/fleetSelectors.ts';

const station = (id: string, online: boolean, version: string | null): EdgeStation => ({
  station_id: id, name: id, cell: id.split('-')[0], online, simulated: false,
  last_seen_at: '2026-11-27T08:00:00Z', models: version ? [{ use_case: 'quality', status: 'loaded',
    model: { registered_model: 'catalog.production.quality', version }, loaded_at: '2026-11-27T08:00:00Z', error: null }] : [],
});

test('le parc ne transforme jamais une version chargée en version à jour', () => {
  const active = station('A-01', true, '4');
  assert.equal(modelState(active, 'quality'), 'Chargé · version souhaitée inconnue');
  assert.equal(modelText(active, 'quality'), 'catalog.production.quality · v4');
  assert.equal(modelState(station('B-01', false, '3'), 'quality'), 'Dernière version connue');
  assert.equal(modelState(station('C-01', true, null), 'quality'), 'État inconnu');
  assert.equal(rawModelText({ kind: 'model.status', use_case: 'quality', model_name: 'local',
    model_version: '0.1.0', package_sha256: null, loaded: true, error: null }), 'local · 0.1.0');
});

test('recherche, filtres et tri restent indépendants des machines absentes', () => {
  const stations = [station('B-02', false, '3'), station('A-01', true, '4')];
  const filters = { query: '', cell: '', model: '', useCase: '', connection: '', version: '', sort: 'station' };
  assert.deepEqual(filterStations(stations, filters).map((s) => s.station_id), ['A-01', 'B-02']);
  assert.deepEqual(filterStations(stations, { ...filters, connection: 'offline', version: '3' })
    .map((s) => s.station_id), ['B-02']);
  assert.deepEqual(filterStations(stations, { ...filters, query: 'inconnu' }), []);
});
