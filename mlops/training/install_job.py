"""Install the Databricks Job of a declared pipeline (SCI-02), from a WORKING template job.

The job definition is copied from an existing, proven job (default
``hovis-quality-industrial-training``: notebook launcher, serverless CPU, no schedule, no
retry) and only the pipeline-specific parts are replaced: job name, script, pinned
environment (``compute.environment`` of pipeline.yaml). The pipeline code is uploaded to the
``code_root`` of the Volume with the same layout as the repository.

DEFAULT = DRY RUN (read-only): template, existing job, base weights, files to upload. Changes
happen only with ``--execute``, ``HOVIS_TRAINING_REMOTE_SETUP=1`` and ``--confirm <job name>``.
Installing a job NEVER launches it: launches go through TrainingService.launch only.

    python -m mlops.training.install_job --pipeline workstation-industrial
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def code_files(script_rel: str, extra: list[str] | None = None) -> list[Path]:
    """The runner's folder (recursively), the package __init__ files above it and the shared
    modules declared by ``job.code_extra`` (repository-relative files, never outside it)."""
    folder = ROOT / Path(script_rel).parent
    files = [
        p
        for p in folder.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix not in (".pyc", ".pt", ".onnx", ".zip", ".jpg", ".png", ".sqlite", ".sqlite3")
    ]
    parent = folder
    while parent != ROOT:
        init = parent / "__init__.py"
        if init.is_file() and init not in files:
            files.append(init)
        parent = parent.parent
    for rel in extra or []:
        f = (ROOT / rel).resolve()
        if not f.is_relative_to(ROOT) or not f.is_file() or f.suffix != ".py":
            raise ValueError(f"code_extra must list Python files of the repository: {rel}")
        if f not in files:
            files.append(f)
    return sorted(files)


def job_settings(template: dict[str, Any], spec) -> dict[str, Any]:
    s = copy.deepcopy(template)
    s["name"] = spec.job["name"]
    s.pop("schedule", None)
    s.pop("trigger", None)
    s["max_concurrent_runs"] = 1
    task = s["tasks"][0]
    task.pop("retry_on_timeout", None)
    task["max_retries"] = 0
    params = task["notebook_task"].setdefault("base_parameters", {})
    params["script"] = spec.job["script"]
    params["args"] = "[]"
    for env in s.get("environments", []):
        env.setdefault("spec", {})["dependencies"] = list(spec.compute.get("environment", []))
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pipeline", required=True)
    ap.add_argument("--template-job", default="hovis-quality-industrial-training")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--confirm", default="")
    args = ap.parse_args(argv)

    from mlops.api.routes import default_connector
    from mlops.training.specs import load_specs

    spec = next((s for s in load_specs() if s.id == args.pipeline), None)
    if spec is None:
        print(f"unknown pipeline {args.pipeline}")
        return 2
    c = default_connector()
    w = c.w
    code_root = spec.job["code_root"]
    script_rel = spec.job["script"].removeprefix(code_root + "/")
    files = code_files(script_rel, spec.job.get("code_extra"))
    jobs = {j.settings.name: j for j in w.jobs.list(name=spec.job["name"])}
    template = next(iter(w.jobs.list(name=args.template_job)), None)
    if template is None:
        print(f"template job {args.template_job} not found")
        return 2
    settings = job_settings(w.jobs.get(template.job_id).settings.as_dict(), spec)

    def exists(path: str | None) -> bool:
        if not path:
            return False
        try:
            w.files.get_metadata(path)
            return True
        except Exception:  # noqa: BLE001 - absent or unreadable
            return False

    print(f"pipeline {spec.id} -> job {spec.job['name']} (template {args.template_job})")
    print(f"  job already exists: {spec.job['name'] in jobs}")
    print(
        f"  base weights {spec.job.get('base_weights')}: "
        f"{'present' if exists(spec.job.get('base_weights')) else 'ABSENT'}"
    )
    print(
        f"  script {spec.job['script']}: "
        f"{'present' if exists(spec.job['script']) else 'absent (will be uploaded)'}"
    )
    print(f"  {len(files)} code file(s) to upload under {code_root}")
    print(
        f"  environment: {len(spec.compute.get('environment', []))} pinned dependencies, "
        "serverless CPU, "
        "no schedule, no retry, max 1 concurrent run"
    )
    if not args.execute:
        print(
            "DRY RUN: nothing changed. Needs --execute, HOVIS_TRAINING_REMOTE_SETUP=1 and "
            f"--confirm {spec.job['name']}"
        )
        print(
            json.dumps(
                {k: settings[k] for k in ("name", "max_concurrent_runs")}, ensure_ascii=False
            )
        )
        return 0
    if os.environ.get("HOVIS_TRAINING_REMOTE_SETUP") != "1" or args.confirm != spec.job["name"]:
        print(f"REFUSED: needs HOVIS_TRAINING_REMOTE_SETUP=1 and --confirm {spec.job['name']}")
        return 3
    import io

    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        w.files.upload(f"{code_root}/{rel}", io.BytesIO(f.read_bytes()), overwrite=True)
    print(f"  {len(files)} code file(s) uploaded")
    if spec.job["name"] in jobs:
        print("  job already exists: definition left unchanged (review it in Databricks)")
    else:
        job_id = w.api_client.do("POST", "/api/2.1/jobs/create", body=settings)["job_id"]
        print(f"  job created: {job_id} (NOT launched; use Training Factory)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
