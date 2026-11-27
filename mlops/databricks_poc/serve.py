"""DBX-00E: create or update the ONE custom serving endpoint and wait until it is READY.

    python -m mlops.databricks_poc.serve --version 1     # explicit numeric version
    python -m mlops.databricks_poc.serve --alias champion

Endpoint ``argos-quality-poc``: CPU, workload size Small (smallest), scale to zero ON.
An existing endpoint is UPDATED (never a second endpoint). "Created" is not "ready": the
script waits (bounded) for state.ready == READY and config_update == NOT_UPDATING.
"""

from __future__ import annotations

import argparse
import sys
import time

from databricks.sdk.errors import NotFound
from databricks.sdk.service.serving import (
    EndpointCoreConfigInput,
    EndpointTag,
    ServedEntityInput,
    ServingModelWorkloadType,
)

from mlops.databricks_poc.common import ENDPOINT, MODEL, save_result, workspace_client

SERVED_NAME = "quality-demo"
MAX_WAIT_S = 50 * 60


def served_entity(version: str) -> ServedEntityInput:
    return ServedEntityInput(
        name=SERVED_NAME,
        entity_name=MODEL,
        entity_version=version,
        workload_size="Small",
        workload_type=ServingModelWorkloadType.CPU,
        scale_to_zero_enabled=True,
    )


def resolve_version(alias: str) -> str:
    import mlflow

    return (
        mlflow.MlflowClient(registry_uri="databricks-uc")
        .get_model_version_by_alias(MODEL, alias)
        .version
    )


def describe(endpoint) -> dict:
    entities = (endpoint.config.served_entities if endpoint.config else None) or []
    pending = endpoint.pending_config.served_entities if endpoint.pending_config else []
    return {
        "ready": endpoint.state.ready.value if endpoint.state and endpoint.state.ready else None,
        "config_update": endpoint.state.config_update.value
        if endpoint.state and endpoint.state.config_update
        else None,
        "served": [
            {
                "name": e.name,
                "version": e.entity_version,
                "workload_size": e.workload_size,
                "scale_to_zero": e.scale_to_zero_enabled,
                "deployment": e.state.deployment.value if e.state and e.state.deployment else None,
                "message": e.state.deployment_state_message if e.state else None,
            }
            for e in entities
        ],
        "pending_versions": [e.entity_version for e in (pending or [])],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--version")
    group.add_argument("--alias")
    args = parser.parse_args(argv)

    w = workspace_client()
    version = args.version or resolve_version(args.alias)
    try:
        w.serving_endpoints.get(ENDPOINT)
        action = "update_config"
        w.serving_endpoints.update_config(ENDPOINT, served_entities=[served_entity(version)])
    except NotFound:
        action = "create"
        w.serving_endpoints.create(
            name=ENDPOINT,
            config=EndpointCoreConfigInput(name=ENDPOINT, served_entities=[served_entity(version)]),
            tags=[
                EndpointTag(key="argos", value="dbx-00-poc"),
                EndpointTag(key="synthetic", value="true"),
            ],
        )
    print(f"{action} requested: {ENDPOINT} -> {MODEL} v{version} (CPU Small, scale to zero)")

    start, last, timeline = time.time(), None, []
    while True:
        state = describe(w.serving_endpoints.get(ENDPOINT))
        key = (
            state["ready"],
            state["config_update"],
            tuple(s["deployment"] for s in state["served"]),
        )
        if key != last:
            elapsed = int(time.time() - start)
            timeline.append({"t_s": elapsed, **state})
            print(
                f"  [{elapsed:>4}s] ready={state['ready']} update={state['config_update']} "
                f"served={state['served']}",
                flush=True,
            )
            last = key
        done = state["config_update"] in ("NOT_UPDATING", "UPDATE_FAILED", "UPDATE_CANCELED")
        if done and (state["config_update"] != "NOT_UPDATING" or state["ready"] == "READY"):
            break
        if time.time() - start > MAX_WAIT_S:
            print("timeout reached while waiting for the endpoint")
            break
        time.sleep(30)

    served_versions = [s["version"] for s in state["served"]]
    ok = (
        state["ready"] == "READY"
        and state["config_update"] == "NOT_UPDATING"
        and version in served_versions
    )
    if not ok:
        try:
            state["build_logs_tail"] = w.serving_endpoints.build_logs(ENDPOINT, SERVED_NAME).logs[
                -3000:
            ]
        except Exception as exc:  # noqa: BLE001
            state["build_logs_tail"] = f"unavailable: {exc}"
        print(state["build_logs_tail"])
    path = save_result(
        f"serving_{action}_v{version}",
        {
            "action": action,
            "requested_version": version,
            "ok": ok,
            "wait_s": int(time.time() - start),
            "final": state,
            "timeline": timeline,
        },
    )
    print(
        f"{'READY' if ok else 'NOT READY'} - serving versions {served_versions} - saved to {path}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
