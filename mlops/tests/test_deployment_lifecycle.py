"""Local-only lifecycle tests. No Databricks client or endpoint is mutated."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mlops.api.deployment_routes import create_deployment_router
from mlops.deployment.contracts import (
    DecisionRequest,
    DeploymentPrepareRequest,
    EndpointSnapshot,
    LifecycleError,
    RollbackPrepareRequest,
    VersionSnapshot,
)
from mlops.deployment.gateway import DatabricksDeploymentGateway, supported_config
from mlops.deployment.service import LifecycleService
from mlops.deployment.store import OperationStore

MODEL = "quality-poc"
UC = "workspace.argos_poc.quality_demo"
ENDPOINT = "argos-quality-poc"


class FakeGateway:
    def __init__(self):
        self.tags = {
            "1": {"argos_approval": "approved"},
            "2": {"argos_approval": "approved"},
            "3": {},
        }
        self.config = {
            "served_entities": [
                {
                    "name": "quality-demo",
                    "entity_name": UC,
                    "entity_version": "1",
                    "workload_size": "Small",
                    "workload_type": "CPU",
                    "scale_to_zero_enabled": True,
                }
            ],
            "traffic_config": {
                "routes": [{"served_entity_name": "quality-demo", "traffic_percentage": 100}]
            },
        }
        self.pending = []
        self.ready = "READY"
        self.config_update = "NOT_UPDATING"
        self.deployment = "DEPLOYMENT_READY"
        self.config_version = 7
        self.calls = 0
        self.fail_update = False
        self.timeout_after_submit = False
        self.read_failure = False
        self.alias = "1"

    def version(self, model_id, version):
        assert model_id == MODEL
        if version not in self.tags:
            raise LifecycleError("version missing", 404)
        return VersionSnapshot(
            model_id=model_id,
            registered_model=UC,
            version=version,
            tags=deepcopy(self.tags[version]),
            run_id="run",
        )

    def endpoint(self, name):
        assert name == ENDPOINT
        if self.read_failure:
            raise RuntimeError("network down")
        return EndpointSnapshot(
            name=name,
            ready=self.ready,
            config_update=self.config_update,
            deployment=self.deployment,
            config_version=self.config_version,
            config=supported_config(deepcopy(self.config)),
            pending_versions=self.pending.copy(),
        )

    def update_endpoint(self, name, config):
        assert name == ENDPOINT
        self.calls += 1
        if self.fail_update:
            raise RuntimeError("remote failure before acknowledgement")
        self.pending = [config["served_entities"][0]["entity_version"]]
        self.config_update = "IN_PROGRESS"
        if self.timeout_after_submit:
            raise TimeoutError("ack lost")

    def finish(self, config):
        self.config = deepcopy(config)
        self.config_version += 1
        self.pending = []
        self.config_update = "NOT_UPDATING"

    def set_decision(self, model_id, version, tags):
        assert model_id == MODEL
        self.tags[version].update(tags)


@pytest.fixture
def lifecycle(tmp_path):
    gateway = FakeGateway()
    store = OperationStore(tmp_path / "operations.sqlite3")
    yield LifecycleService(gateway, store, {MODEL: ENDPOINT}), gateway, store
    store.close()


def request(version="2"):
    return DeploymentPrepareRequest(
        model_id=MODEL,
        version=version,
        endpoint=ENDPOINT,
        reason="Candidate passed validation",
        author_declared="demo",
    )


def test_decisions_and_served_rejection(lifecycle):
    service, gateway, store = lifecycle
    with pytest.raises(LifecycleError, match="currently served"):
        service.decide(
            MODEL,
            "1",
            DecisionRequest(decision="rejected", reason="Bad result", author_declared="demo"),
        )
    record = service.decide(
        MODEL,
        "1",
        DecisionRequest(
            decision="rejected",
            reason="Bad result",
            author_declared="demo",
            acknowledge_served_rejection=True,
        ),
    )
    assert record.status == "applied" and record.requires_serving_action
    assert gateway.config["served_entities"][0]["entity_version"] == "1"
    assert gateway.alias == "1"
    service.decide(
        MODEL, "1", DecisionRequest(decision="approved", reason="Retested", author_declared="demo")
    )
    assert len(store.decisions(MODEL, "1")) == 2
    state = service.decision_state(MODEL, "1")
    assert state["decision"] == "approved" and state["authenticated_identity"] is None
    reopened = OperationStore(store.path)
    assert len(reopened.decisions(MODEL, "1")) == 2
    reopened.close()


def test_preconditions_config_and_concurrency(lifecycle):
    service, gateway, _ = lifecycle
    with pytest.raises(LifecycleError, match="not approved"):
        service.prepare(request("3"))
    gateway.config["served_entities"].append(deepcopy(gateway.config["served_entities"][0]))
    with pytest.raises(LifecycleError, match="exactly one"):
        service.prepare(request())
    gateway.config["served_entities"].pop()
    operation = service.prepare(request())
    with pytest.raises(LifecycleError, match="operation"):
        service.prepare(request())
    assert operation.requested_config["served_entities"][0]["workload_size"] == "Small"
    assert operation.requested_config["served_entities"][0]["scale_to_zero_enabled"]
    assert operation.requested_config["traffic_config"] == gateway.config["traffic_config"]
    gateway.config_version += 1
    with pytest.raises(LifecycleError, match="config version changed"):
        service.confirm(operation.operation_id, operation.confirmation)
    assert gateway.calls == 0


def test_restart_reconcile_rollback_and_no_alias_move(lifecycle):
    service, gateway, store = lifecycle
    operation = service.prepare(request())
    sent = service.confirm(operation.operation_id, operation.confirmation)
    assert sent.status == "updating" and gateway.calls == 1
    assert service.confirm(operation.operation_id, operation.confirmation).status == "updating"
    assert gateway.calls == 1
    restarted_store = OperationStore(store.path)
    restarted = LifecycleService(gateway, restarted_store, {MODEL: ENDPOINT})
    assert restarted.reconcile(operation.operation_id).status == "updating"
    gateway.finish(sent.requested_config)
    verified = restarted.reconcile(operation.operation_id)
    assert verified.status == "succeeded" and verified.verification["active_version"] == "2"
    assert verified.inference_tested is False and gateway.alias == "1"
    rollback = restarted.prepare_rollback(
        RollbackPrepareRequest(
            source_operation_id=operation.operation_id,
            reason="Return to verified state",
            author_declared="demo",
        )
    )
    assert rollback.kind == "rollback" and rollback.version == "1"
    restarted.confirm(rollback.operation_id, rollback.confirmation)
    gateway.finish(rollback.requested_config)
    assert restarted.reconcile(rollback.operation_id).status == "succeeded"
    assert gateway.alias == "1" and gateway.calls == 2
    restarted_store.close()


def test_timeout_and_remote_failure_do_not_resubmit(lifecycle):
    service, gateway, _ = lifecycle
    operation = service.prepare(request())
    gateway.timeout_after_submit = True
    uncertain = service.confirm(operation.operation_id, operation.confirmation)
    assert uncertain.status == "uncertain" and gateway.calls == 1
    gateway.read_failure = True
    assert service.reconcile(operation.operation_id).status == "uncertain"
    gateway.read_failure = False
    gateway.finish(uncertain.requested_config)
    assert service.reconcile(operation.operation_id).status == "succeeded"
    assert service.confirm(operation.operation_id, operation.confirmation).status == "succeeded"
    assert gateway.calls == 1


def test_failed_remote_update_and_rollback_requires_approval(lifecycle):
    service, gateway, _ = lifecycle
    operation = service.prepare(request())
    gateway.fail_update = True
    assert service.confirm(operation.operation_id, operation.confirmation).status == "uncertain"
    gateway.config_update = "UPDATE_FAILED"
    assert service.reconcile(operation.operation_id).status == "failed"
    with pytest.raises(LifecycleError, match="verified deployment"):
        service.prepare_rollback(
            RollbackPrepareRequest(
                source_operation_id=operation.operation_id,
                reason="Undo failure",
                author_declared="demo",
            )
        )


def test_rollback_blocks_when_previous_version_is_rejected(lifecycle):
    service, gateway, _ = lifecycle
    operation = service.prepare(request())
    sent = service.confirm(operation.operation_id, operation.confirmation)
    gateway.finish(sent.requested_config)
    assert service.reconcile(operation.operation_id).status == "succeeded"
    gateway.tags["1"]["argos_approval"] = "rejected"
    with pytest.raises(LifecycleError, match="not approved"):
        service.prepare_rollback(
            RollbackPrepareRequest(
                source_operation_id=operation.operation_id,
                reason="Undo deployment",
                author_declared="demo",
            )
        )
    assert gateway.calls == 1


def test_unsupported_topology():
    gateway = FakeGateway()
    config = deepcopy(gateway.config)
    config["traffic_config"]["routes"].append(config["traffic_config"]["routes"][0])
    with pytest.raises(LifecycleError, match="multi-route"):
        supported_config(config)
    config = deepcopy(gateway.config)
    config["served_entities"][0]["environment_vars"] = {"SECRET": "value"}
    with pytest.raises(LifecycleError, match="unsupported settings"):
        supported_config(config)


def test_databricks_gateway_reads_directly_and_submits_preserved_config():
    config = FakeGateway().config
    captures = []
    endpoint_config = SimpleNamespace(
        as_dict=lambda: deepcopy(config),
        served_entities=[SimpleNamespace(state=SimpleNamespace(deployment="DEPLOYMENT_READY"))],
        config_version=7,
    )
    endpoint = SimpleNamespace(
        config=endpoint_config,
        pending_config=None,
        state=SimpleNamespace(ready="READY", config_update="NOT_UPDATING"),
    )
    serving = SimpleNamespace(
        get=lambda name: endpoint,
        update_config=lambda name, **kwargs: captures.append((name, kwargs)),
    )
    invalidated = []
    connector = SimpleNamespace(
        _call=lambda fn, what: fn(),
        w=SimpleNamespace(serving_endpoints=serving),
        reads=SimpleNamespace(invalidate=lambda *keys: invalidated.extend(keys)),
    )
    gateway = DatabricksDeploymentGateway(connector)
    snapshot = gateway.endpoint(ENDPOINT)
    assert snapshot.config == config and snapshot.config_version == 7
    desired = deepcopy(snapshot.config)
    desired["served_entities"][0]["entity_version"] = "2"
    gateway.update_endpoint(ENDPOINT, desired)
    assert len(captures) == 1 and captures[0][0] == ENDPOINT
    submitted = captures[0][1]
    assert submitted["served_entities"][0].as_dict() == desired["served_entities"][0]
    assert submitted["traffic_config"].as_dict() == desired["traffic_config"]
    assert "endpoint:argos-quality-poc" in invalidated


def test_api_routes_use_fake_service(lifecycle):
    service, gateway, _ = lifecycle
    app = FastAPI()
    app.include_router(create_deployment_router(lambda: service), prefix="/api")
    client = TestClient(app)
    prepared = client.post("/api/mlops/deployments/prepare", json=request().model_dump())
    assert prepared.status_code == 201, prepared.json()
    operation = prepared.json()
    assert (
        client.post(
            f"/api/mlops/deployments/{operation['operation_id']}/confirm",
            json={"confirmation": "wrong"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/mlops/deployments/{operation['operation_id']}/confirm",
            json={"confirmation": operation["confirmation"]},
        ).status_code
        == 202
    )
    assert gateway.calls == 1
    assert client.get("/api/mlops/deployments").json()[0]["status"] == "updating"
    assert len(client.get(f"/api/mlops/deployments/{operation['operation_id']}/events").json()) == 3
