"""DBX-00A: real capability audit of the Databricks workspace (read-only calls only).

    python -m mlops.databricks_poc.audit

Levels reported for each capability:
  visible   -> the service exists in the SDK / workspace
  readable  -> a read call succeeded with our identity
  creatable -> proven only later by the POC steps that create resources
  executed  -> proven only later by a real execution (job run, endpoint READY, inference)
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from mlops.databricks_poc.common import CATALOG, save_result, workspace_client

GPU_MARKERS = ("g4dn", "g5", "g6", "p3", "p4", "p5", "gpu", "a10", "a100", "h100", "t4")


def probe(results: dict, name: str, call: Callable[[], Any]) -> Any:
    try:
        value = call()
        results[name] = {"readable": True, "detail": value}
        print(f"[READ OK] {name:<34} {str(value)[:110]}")
        return value
    except Exception as exc:  # noqa: BLE001 - an audit must report every failure
        message = f"{type(exc).__name__}: {str(exc)[:300]}"
        results[name] = {"readable": False, "error": message}
        print(f"[FAIL]    {name:<34} {message[:110]}")
        return None


def main() -> int:
    w = workspace_client()
    r: dict[str, Any] = {}

    probe(
        r,
        "auth.current_user",
        lambda: {
            "active": w.current_user.me().active,
            "is_admin": any(g.display == "admins" for g in (w.current_user.me().groups or [])),
        },
    )
    probe(r, "workspace.id", lambda: w.get_workspace_id())
    probe(r, "workspace.list(/Shared)", lambda: len(list(w.workspace.list("/Shared"))))
    probe(r, "jobs.list", lambda: len(list(w.jobs.list(limit=25))))
    probe(r, "unity_catalog.catalogs", lambda: [c.name for c in w.catalogs.list()])
    probe(
        r,
        f"unity_catalog.schemas({CATALOG})",
        lambda: [s.name for s in w.schemas.list(catalog_name=CATALOG)],
    )
    probe(
        r,
        "volumes.list(workspace.default)",
        lambda: [v.name for v in w.volumes.list(catalog_name=CATALOG, schema_name="default")],
    )
    probe(
        r,
        "sql.warehouses",
        lambda: [
            {
                "name": x.name,
                "id": x.id,
                "state": str(x.state),
                "size": x.cluster_size,
                "serverless": x.enable_serverless_compute,
            }
            for x in w.warehouses.list()
        ],
    )
    probe(
        r,
        "mlflow.experiments(databricks)",
        lambda: len(list(w.experiments.search_experiments(max_results=50))),
    )
    probe(
        r,
        "uc.registered_models(workspace)",
        lambda: [m.full_name for m in w.registered_models.list(catalog_name=CATALOG)],
    )
    probe(
        r,
        "serving.endpoints",
        lambda: [
            {
                "name": e.name,
                "state": str(e.state.ready) if e.state else None,
                "foundation": (e.name or "").startswith("databricks-"),
            }
            for e in w.serving_endpoints.list()
        ],
    )
    node_types = probe(
        r,
        "clusters.node_types",
        lambda: [n.node_type_id for n in w.clusters.list_node_types().node_types],
    )
    if node_types is not None:
        gpus = [n for n in node_types if any(m in n.lower() for m in GPU_MARKERS)]
        r["gpu.node_types_listed"] = {"readable": True, "detail": gpus[:20], "count": len(gpus)}
        print(f"[INFO]    {'gpu node types listed':<34} {len(gpus)} (listed != usable on a trial)")
    probe(
        r,
        "clusters.spark_versions(ml/gpu)",
        lambda: [
            v.key for v in w.clusters.spark_versions().versions if "gpu" in v.key or "-ml-" in v.key
        ][:10],
    )
    probe(r, "data_quality.list_monitor", lambda: len(list(w.data_quality.list_monitor())))
    probe(
        r, "quality_monitors (lakehouse)", lambda: "service present in SDK (needs a table to query)"
    )

    path = save_result("audit", r)
    failures = [k for k, v in r.items() if not v.get("readable")]
    print(f"\n{len(r) - len(failures)} readable, {len(failures)} failed. Saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
