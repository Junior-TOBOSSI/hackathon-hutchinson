"""Declarative training pipelines: one ``mlops/pipelines/<id>/pipeline.yaml`` per pipeline.

Adding a pipeline (EPI, Behavior, Workstation...) = adding a folder with its YAML and its
code; Training Factory needs no change. A pipeline is EXECUTABLE only when every requirement
is really met (local code present, remote job existing); otherwise it is listed with reasons.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

PIPELINES_DIR = Path(__file__).resolve().parents[1] / "pipelines"


class ParamSpec(BaseModel):
    name: str
    type: Literal["int", "float", "bool", "str"]
    default: Any
    min: float | None = None
    max: float | None = None
    level: Literal["basic", "advanced", "imposed"]
    label: str
    help: str | None = None
    choices: list[str] = Field(default_factory=list)


class DatasetRequirement(BaseModel):
    families: list[str]
    annotation_format: str = "classification"
    image_extensions: list[str]
    required_splits: list[str]
    split_names: dict[str, str] = Field(default_factory=dict)
    group_field: str | None = None
    group_required: bool = False


class PipelineSpec(BaseModel):
    id: str
    name: str
    use_case: str
    task: str
    architecture: str
    description: str
    code: dict[str, str]
    classes: list[str]
    dataset: DatasetRequirement
    parameters: list[ParamSpec]
    compute: dict[str, Any]
    job: dict[str, Any]
    entrypoints: dict[str, str]
    outputs: list[str]
    mlflow: dict[str, Any]
    evaluation: dict[str, Any]
    folder: str = ""

    def param(self, name: str) -> ParamSpec | None:
        return next((p for p in self.parameters if p.name == name), None)

    # SCI-03: a pipeline may register into ONE model per value of a parameter (Workstation:
    # one model per section). Versions of different sections are never in the same registered
    # model, so they are never compared, approved or promoted as interchangeable.
    def registered_models(self) -> list[str]:
        per = self.mlflow.get("registered_models")
        return list(per.values()) if per else [self.mlflow["registered_model"]]

    def registered_model_for(self, parameters: dict[str, Any] | None) -> str:
        per = self.mlflow.get("registered_models")
        if not per:
            return self.mlflow["registered_model"]
        key = (parameters or {}).get(self.mlflow["registered_model_by"])
        if key not in per:
            raise ValueError(f"no registered model for {self.mlflow['registered_model_by']}={key}")
        return per[key]

    def registers_into(self, uc_name: str) -> bool:
        return uc_name in self.registered_models()


def registers_into(spec: Any, uc_name: str) -> bool:
    """True if the pipeline registers into this UC model (one model or one per section)."""
    mlflow = getattr(spec, "mlflow", {}) or {}
    per = mlflow.get("registered_models")
    return uc_name in per.values() if per else mlflow.get("registered_model") == uc_name


class Requirement(BaseModel):
    id: str
    label: str
    ok: bool
    detail: str | None = None


class PipelineView(BaseModel):
    spec: PipelineSpec
    executable: bool
    requirements: list[Requirement]


def load_specs(root: Path = PIPELINES_DIR) -> list[PipelineSpec]:
    specs = []
    for file in sorted(root.glob("*/pipeline.yaml")):
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
        specs.append(PipelineSpec(**data, folder=str(file.parent)))
    ids = [s.id for s in specs]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate pipeline ids: {ids}")
    return specs


def requirements(spec: PipelineSpec, job_names: set[str] | None) -> list[Requirement]:
    """Real checks only. ``job_names`` = names of the existing Databricks jobs (None: unknown)."""
    out = []
    kit = (
        Path(__file__).resolve().parents[2] / spec.code["path"]
        if spec.code.get("path")
        else Path(spec.folder) / "kit"
    )
    needed = [
        e.split(" ")[0].removeprefix("kit/")
        for e in spec.entrypoints.values()
        if e.startswith("kit/")
    ]
    if needed or spec.code.get("repo") != "local":
        missing = [n for n in needed if not (kit / n).is_file()]
        out.append(
            Requirement(
                id="code",
                label="Code du pipeline présent",
                ok=not missing and kit.is_dir(),
                detail=f"manquant : {', '.join(missing)}" if missing else spec.code.get("version"),
            )
        )
    name = spec.job.get("name")
    if job_names is None:
        out.append(Requirement(id="job", label="Job Databricks", ok=False, detail="état inconnu"))
    else:
        out.append(
            Requirement(
                id="job",
                label=f"Job Databricks « {name} »",
                ok=name in job_names,
                detail=None
                if name in job_names
                else "job non créé (création soumise à autorisation)",
            )
        )
    out.append(
        Requirement(
            id="compute",
            label="Calcul autorisé",
            ok=not spec.compute.get("gpu", False),
            detail="serverless CPU" if not spec.compute.get("gpu") else "GPU non autorisé",
        )
    )
    return out


def view(spec: PipelineSpec, job_names: set[str] | None) -> PipelineView:
    reqs = requirements(spec, job_names)
    return PipelineView(spec=spec, executable=all(r.ok for r in reqs), requirements=reqs)
