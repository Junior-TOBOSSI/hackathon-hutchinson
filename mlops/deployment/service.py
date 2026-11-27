"""Lifecycle rules: explicit approval, guarded Serving updates and safe reconciliation."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from mlops.deployment.contracts import (
    DecisionRecord,
    DecisionRequest,
    DeploymentOperation,
    DeploymentPrepareRequest,
    EndpointSnapshot,
    LifecycleError,
    RollbackPrepareRequest,
)
from mlops.deployment.gateway import APPROVAL_TAG, DeploymentGateway
from mlops.deployment.store import OperationStore, now

PREPARE_MINUTES = 10
OPEN = {"requesting", "updating", "verifying", "uncertain"}


def fingerprint(config: dict) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def active_version(snapshot: EndpointSnapshot) -> str:
    return str(snapshot.config["served_entities"][0]["entity_version"])


def ready(snapshot: EndpointSnapshot) -> bool:
    return (
        snapshot.ready == "READY"
        and snapshot.config_update == "NOT_UPDATING"
        and snapshot.deployment == "DEPLOYMENT_READY"
        and not snapshot.pending_versions
    )


class LifecycleService:
    def __init__(
        self,
        gateway: DeploymentGateway,
        store: OperationStore,
        targets: dict[str, str | None],
        allowed_endpoints: set[str] | None = None,
    ):
        self.gateway = gateway
        self.store = store
        self.targets = targets
        self.allowed_endpoints = allowed_endpoints or {"argos-quality-poc"}

    def _target(self, model_id: str, endpoint: str) -> None:
        if model_id not in self.targets:
            raise LifecycleError("model is not managed by HOVIS", 404)
        if endpoint not in self.allowed_endpoints or self.targets[model_id] != endpoint:
            raise LifecycleError("endpoint is outside the authorized deployment scope", 403)

    def _version(self, model_id: str, version: str):
        if not version.isdigit():
            raise LifecycleError("a numeric model version is required", 400)
        result = self.gateway.version(model_id, version)
        if result.version != version:
            raise LifecycleError("registry returned another model version")
        return result

    def _approved(self, model_id: str, version: str):
        result = self._version(model_id, version)
        if result.tags.get(APPROVAL_TAG) != "approved":
            raise LifecycleError(f"model version {version} is not approved")
        return result

    def _endpoint(self, endpoint: str, registered_model: str) -> EndpointSnapshot:
        snap = self.gateway.endpoint(endpoint)  # direct read: never a stale cache value
        if snap.name != endpoint:
            raise LifecycleError("endpoint response names another target")
        entity = snap.config["served_entities"][0]
        if entity["entity_name"] != registered_model:
            raise LifecycleError("endpoint serves another registered model")
        if not ready(snap):
            raise LifecycleError("endpoint is not ready or a config update is in progress")
        return snap

    def _make_operation(
        self,
        kind: str,
        request: DeploymentPrepareRequest | RollbackPrepareRequest,
        model_id: str,
        registered_model: str,
        version: str,
        endpoint: str,
        snapshot: EndpointSnapshot,
        desired: dict,
        source_operation_id: str | None = None,
    ) -> DeploymentOperation:
        stamp = now()
        verb = "DEPLOY" if kind == "deploy" else "ROLLBACK"
        return DeploymentOperation(
            operation_id=uuid.uuid4().hex,
            kind=kind,
            model_id=model_id,
            registered_model=registered_model,
            version=version,
            endpoint=endpoint,
            previous_version=active_version(snapshot),
            previous_config=snapshot.config,
            requested_config=desired,
            expected_fingerprint=fingerprint(snapshot.config),
            expected_config_version=snapshot.config_version,
            reason=request.reason,
            author_declared=request.author_declared,
            role_declared=request.role_declared,
            source_operation_id=source_operation_id,
            status="prepared",
            confirmation=f"{verb} {endpoint} v{version}",
            created_at=stamp,
            updated_at=stamp,
            expires_at=(datetime.now(UTC) + timedelta(minutes=PREPARE_MINUTES)).isoformat(
                timespec="seconds"
            ),
        )

    def _free_target(self, endpoint: str) -> None:
        self.store.expire_prepared()
        active = self.store.active(endpoint)
        if active and active.status in OPEN:
            self.reconcile(active.operation_id)
            active = self.store.active(endpoint)
        if active:
            raise LifecycleError(
                f"operation {active.operation_id} is {active.status} on {endpoint}"
            )

    def prepare(self, request: DeploymentPrepareRequest) -> DeploymentOperation:
        self._target(request.model_id, request.endpoint)
        self._free_target(request.endpoint)
        version = self._approved(request.model_id, request.version)
        snap = self._endpoint(request.endpoint, version.registered_model)
        if active_version(snap) == request.version:
            raise LifecycleError("requested version is already active")
        desired = json.loads(json.dumps(snap.config))
        desired["served_entities"][0]["entity_version"] = request.version
        return self.store.insert(
            self._make_operation(
                "deploy",
                request,
                request.model_id,
                version.registered_model,
                request.version,
                request.endpoint,
                snap,
                desired,
            )
        )

    def prepare_rollback(self, request: RollbackPrepareRequest) -> DeploymentOperation:
        source = self.store.get(request.source_operation_id)
        if source.status != "succeeded" or source.kind != "deploy":
            raise LifecycleError("rollback source must be a verified deployment")
        self._target(source.model_id, source.endpoint)
        self._free_target(source.endpoint)
        version = self._approved(source.model_id, source.previous_version)
        snap = self._endpoint(source.endpoint, version.registered_model)
        if fingerprint(snap.config) != fingerprint(source.requested_config):
            raise LifecycleError(
                "current endpoint configuration differs from the verified deployment"
            )
        if active_version(snap) != source.version:
            raise LifecycleError("current endpoint version differs from the verified deployment")
        return self.store.insert(
            self._make_operation(
                "rollback",
                request,
                source.model_id,
                version.registered_model,
                source.previous_version,
                source.endpoint,
                snap,
                source.previous_config,
                source.operation_id,
            )
        )

    def confirm(self, operation_id: str, confirmation: str) -> DeploymentOperation:
        operation = self.store.get(operation_id)
        if operation.status in OPEN | {"succeeded"}:
            return operation  # idempotent: never submit the same remote update twice
        if operation.status != "prepared":
            raise LifecycleError(f"operation is {operation.status}; it cannot be confirmed")
        if operation.expires_at < now():
            self.store.transition(operation_id, {"prepared"}, "expired")
            raise LifecycleError("confirmation window expired")
        if confirmation != operation.confirmation:
            raise LifecycleError("confirmation text does not match the prepared operation", 400)
        try:
            version = self._approved(operation.model_id, operation.version)
            snap = self._endpoint(operation.endpoint, version.registered_model)
            if fingerprint(snap.config) != operation.expected_fingerprint:
                raise LifecycleError("endpoint config changed since preparation")
            if snap.config_version != operation.expected_config_version:
                raise LifecycleError("endpoint config version changed since preparation")
        except Exception as exc:
            self.store.transition(
                operation_id, {"prepared"}, "failed", error=str(exc), completed_at=now()
            )
            raise
        self.store.transition(operation_id, {"prepared"}, "requesting", submitted_at=now())
        try:
            self.gateway.update_endpoint(operation.endpoint, operation.requested_config)
        except Exception as exc:  # a timeout may follow a successful remote submission
            return self.store.transition(
                operation_id,
                {"requesting"},
                "uncertain",
                "remote request outcome unknown; inspect before retrying",
                error=str(exc),
            )
        return self.store.transition(operation_id, {"requesting"}, "updating")

    def reconcile(self, operation_id: str) -> DeploymentOperation:
        operation = self.store.get(operation_id)
        if operation.status not in OPEN:
            return operation
        try:
            snap = self.gateway.endpoint(operation.endpoint)
        except Exception as exc:
            if operation.status == "uncertain":
                return operation
            return self.store.transition(
                operation_id,
                {operation.status},
                "uncertain",
                "cannot read remote state",
                error=str(exc),
            )
        verification = {
            "checked_at": now(),
            "ready": snap.ready,
            "config_update": snap.config_update,
            "deployment": snap.deployment,
            "config_version": snap.config_version,
            "active_version": active_version(snap),
            "pending_versions": snap.pending_versions,
            "configuration_matches": fingerprint(snap.config)
            == fingerprint(operation.requested_config),
            "inference_tested": False,
        }
        if snap.config_update in {"UPDATE_FAILED", "UPDATE_CANCELED"}:
            return self.store.transition(
                operation_id,
                {operation.status},
                "failed",
                "Databricks update failed",
                verification=verification,
                error=snap.config_update,
                completed_at=now(),
            )
        if (
            verification["configuration_matches"]
            and ready(snap)
            and active_version(snap) == operation.version
        ):
            return self.store.transition(
                operation_id,
                {operation.status},
                "succeeded",
                "active configuration verified",
                verification=verification,
                error=None,
                completed_at=now(),
            )
        next_status = (
            "updating"
            if snap.config_update == "IN_PROGRESS"
            else "verifying"
            if verification["configuration_matches"]
            else "uncertain"
        )
        if next_status == operation.status:
            return operation
        return self.store.transition(
            operation_id,
            {operation.status},
            next_status,
            "remote state does not yet prove the requested version",
            verification=verification,
        )

    def decide(self, model_id: str, version: str, request: DecisionRequest) -> DecisionRecord:
        current = self._version(model_id, version)
        endpoint = self.targets.get(model_id)
        served: bool | None = None
        if endpoint and request.decision == "rejected":
            snap = self.gateway.endpoint(endpoint)
            served = (
                snap.config["served_entities"][0]["entity_name"] == current.registered_model
                and active_version(snap) == version
            )
        if request.decision == "rejected" and served and not request.acknowledge_served_rejection:
            raise LifecycleError(
                "version is currently served; explicitly acknowledge that rejection "
                "will not stop it"
            )
        stamp = now()
        record = self.store.insert_decision(
            DecisionRecord(
                decision_id=uuid.uuid4().hex,
                model_id=model_id,
                version=version,
                decision=request.decision,
                reason=request.reason,
                author_declared=request.author_declared,
                role_declared=request.role_declared,
                served_when_decided=served,
                status="requesting",
                created_at=stamp,
                requires_serving_action=bool(served) and request.decision == "rejected",
            )
        )
        tags = {
            "argos_decision_reason": request.reason,
            "argos_decision_at": stamp,
            "argos_decision_author_declared": request.author_declared,
            "argos_decision_role_declared": request.role_declared,
            APPROVAL_TAG: request.decision,
        }
        try:
            self.gateway.set_decision(model_id, version, tags)
            actual = self._version(model_id, version)
            if any(actual.tags.get(k) != value for k, value in tags.items()):
                raise LifecycleError("remote decision tags did not verify")
        except Exception as exc:
            return self.store.update_decision(
                record.decision_id, status="uncertain", error=str(exc)
            )
        return self.store.update_decision(record.decision_id, status="applied", completed_at=now())

    def decision_state(self, model_id: str, version: str) -> dict:
        actual = self._version(model_id, version)
        value = actual.tags.get(APPROVAL_TAG)
        endpoint = self.targets.get(model_id)
        served = False
        if endpoint:
            snap = self.gateway.endpoint(endpoint)
            served = (
                snap.config["served_entities"][0]["entity_name"] == actual.registered_model
                and active_version(snap) == version
            )
        return {
            "model_id": model_id,
            "version": version,
            "decision": value if value in ("approved", "rejected") else "pending",
            "reason": actual.tags.get("argos_decision_reason"),
            "decided_at": actual.tags.get("argos_decision_at"),
            "author_declared": actual.tags.get("argos_decision_author_declared"),
            "role_declared": actual.tags.get("argos_decision_role_declared"),
            "authenticated_identity": None,
            "currently_served": served,
            "requires_serving_action": served and value == "rejected",
            "history": self.store.decisions(model_id, version),
        }
