"""Direct Databricks reads and narrowly scoped Serving writes.

No read-cache fallback is used for preconditions or verification.
"""

from __future__ import annotations

from typing import Protocol

from mlops.databricks.connector import DatabricksConnector
from mlops.deployment.contracts import (
    EndpointSnapshot,
    LifecycleError,
    VersionSnapshot,
)

APPROVAL_TAG = "argos_approval"
ENTITY_FIELDS = {
    "name",
    "entity_name",
    "entity_version",
    "workload_size",
    "workload_type",
    "scale_to_zero_enabled",
}
ENTITY_METADATA = {"state", "creator", "creation_timestamp", "last_updated_timestamp"}


class DeploymentGateway(Protocol):
    def version(self, model_id: str, version: str) -> VersionSnapshot: ...
    def endpoint(self, name: str) -> EndpointSnapshot: ...
    def update_endpoint(self, name: str, config: dict) -> None: ...
    def set_decision(self, model_id: str, version: str, tags: dict[str, str]) -> None: ...


def _value(value) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def supported_config(raw: dict) -> dict:
    """Copy only a single custom-model topology that can be replayed exactly."""
    if raw.get("served_models") or raw.get("auto_capture_config"):
        raise LifecycleError(
            "endpoint topology contains unsupported legacy model or capture config"
        )
    if set(raw) - {
        "config_version",
        "served_entities",
        "served_models",
        "traffic_config",
        "auto_capture_config",
    }:
        raise LifecycleError("endpoint has configuration fields outside the MVP allowlist")
    entities = raw.get("served_entities") or []
    if len(entities) != 1:
        raise LifecycleError("MVP requires exactly one served entity")
    entity = entities[0]
    unsupported = {
        k for k, v in entity.items() if k not in ENTITY_FIELDS | ENTITY_METADATA and v is not None
    }
    if unsupported:
        raise LifecycleError(f"served entity has unsupported settings: {sorted(unsupported)}")
    copy = {k: entity[k] for k in ENTITY_FIELDS if k in entity and entity[k] is not None}
    required = {"name", "entity_name", "entity_version", "workload_size", "scale_to_zero_enabled"}
    if not required.issubset(copy) or not str(copy["entity_version"]).isdigit():
        raise LifecycleError("served entity lacks required custom-model settings")
    traffic = raw.get("traffic_config")
    if traffic:
        routes = traffic.get("routes") or []
        if len(routes) != 1 or routes[0].get("traffic_percentage") != 100:
            raise LifecycleError("MVP cannot preserve multi-route or split traffic")
        route = routes[0]
        if set(route) - {"served_entity_name", "served_model_name", "traffic_percentage"}:
            raise LifecycleError("traffic route contains unsupported fields")
        if (route.get("served_entity_name") or route.get("served_model_name")) != copy["name"]:
            raise LifecycleError("traffic route does not target the sole served entity")
        return {"served_entities": [copy], "traffic_config": {"routes": [route.copy()]}}
    return {"served_entities": [copy]}


class DatabricksDeploymentGateway:
    def __init__(self, connector: DatabricksConnector):
        self.c = connector

    def version(self, model_id: str, version: str) -> VersionSnapshot:
        if not version.isdigit():
            raise LifecycleError("model version must be numeric", 400)
        managed = self.c.managed(model_id)
        v = self.c._call(
            lambda: self.c.mlflow.get_model_version(managed.uc_name, version),
            f"model version {managed.uc_name}/{version}",
        )
        return VersionSnapshot(
            model_id=model_id,
            registered_model=managed.uc_name,
            version=str(v.version),
            tags=dict(v.tags or {}),
            run_id=v.run_id or None,
        )

    def endpoint(self, name: str) -> EndpointSnapshot:
        e = self.c._call(lambda: self.c.w.serving_endpoints.get(name), f"endpoint {name}")
        if e.config is None:
            raise LifecycleError("endpoint has no active config")
        raw = e.config.as_dict()
        config = supported_config(raw)
        entity = e.config.served_entities[0]
        pending = (
            e.pending_config.served_entities
            if e.pending_config and e.pending_config.served_entities
            else []
        )
        return EndpointSnapshot(
            name=name,
            ready=_value(e.state.ready) if e.state else None,
            config_update=_value(e.state.config_update) if e.state else None,
            deployment=_value(entity.state.deployment) if entity.state else None,
            config_version=e.config.config_version,
            config=config,
            pending_versions=[str(p.entity_version) for p in pending if p.entity_version],
        )

    def update_endpoint(self, name: str, config: dict) -> None:
        from databricks.sdk.service.serving import ServedEntityInput, TrafficConfig

        safe = supported_config(config)
        self.c._call(
            lambda: self.c.w.serving_endpoints.update_config(
                name,
                served_entities=[ServedEntityInput.from_dict(safe["served_entities"][0])],
                traffic_config=TrafficConfig.from_dict(safe["traffic_config"])
                if safe.get("traffic_config")
                else None,
            ),
            f"update endpoint {name}",
        )
        # The SDK call only submits the update; it does not prove a ready endpoint.
        self.c.reads.invalidate(f"endpoint:{name}", "endpoints:")

    def set_decision(self, model_id: str, version: str, tags: dict[str, str]) -> None:
        managed = self.c.managed(model_id)
        # The state tag is LAST: partial metadata writes cannot claim an applied decision.
        for key, value in [
            *[(k, v) for k, v in tags.items() if k != APPROVAL_TAG],
            (APPROVAL_TAG, tags[APPROVAL_TAG]),
        ]:
            self.c._call(
                lambda k=key, val=value: self.c.mlflow.set_model_version_tag(
                    managed.uc_name, version, k, val
                ),
                f"version tag {key}",
            )
        self.c.reads.invalidate(f"versions:{model_id}", "overview")
