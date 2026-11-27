import assert from 'node:assert/strict';
import { test } from 'node:test';
import { deploymentApi } from '../src/api/deployment.ts';

test('les actions envoient les contrats DBX-06B à un service simulé uniquement', async () => {
  const original = globalThis.fetch;
  const calls: Array<{ url: string; method: string; body: unknown }> = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(String(init.body)) : null });
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  try {
    await deploymentApi.decide('candidate-A', '12', { decision: 'rejected', reason: 'Évaluation insuffisante',
      author_declared: 'jury', acknowledge_served_rejection: true });
    await deploymentApi.prepare({ model_id: 'candidate-A', version: '12', endpoint: 'argos-quality-poc',
      reason: 'Déploiement validé', author_declared: 'jury' });
    await deploymentApi.confirm('operation-1', 'DEPLOY argos-quality-poc v12');
    await deploymentApi.prepareRollback('operation-1', 'Retour explicite', 'jury');
    await deploymentApi.history();
    await deploymentApi.edgeStations();
    assert.equal(calls[0].url, '/api/mlops/registry/candidate-A/versions/12/decisions');
    assert.equal(calls[0].method, 'POST');
    assert.deepEqual(calls[0].body, { decision: 'rejected', reason: 'Évaluation insuffisante',
      author_declared: 'jury', acknowledge_served_rejection: true });
    assert.equal(calls[1].url, '/api/mlops/deployments/prepare');
    assert.equal(calls[2].url, '/api/mlops/deployments/operation-1/confirm');
    assert.equal(calls[3].url, '/api/mlops/deployments/rollback/prepare');
    assert.equal(calls[4].method, 'GET');
    assert.equal(calls[5].url, '/api/v1/stations');
  } finally { globalThis.fetch = original; }
});

test('une erreur du service simulé n’est jamais transformée en succès', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Version non approuvée' }),
    { status: 409, headers: { 'Content-Type': 'application/json' } });
  try { await assert.rejects(deploymentApi.prepare({ model_id: 'candidate-A', version: '12',
    endpoint: 'argos-quality-poc', reason: 'Test local', author_declared: 'jury' }), /Version non approuvée/); }
  finally { globalThis.fetch = original; }
});
