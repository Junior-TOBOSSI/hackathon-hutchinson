"""Dataset resolution (independent catalogue) and REAL compatibility checks before a launch.

Every check shown in Training Factory is computed here from the published manifest and the
pipeline declaration; a blocking failure forbids the launch.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel

from mlops.training.specs import PipelineSpec

SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Check(BaseModel):
    id: str
    label: str
    status: Literal["ok", "warning", "error"]
    detail: str | None = None


class DatasetPreview(BaseModel):
    """What the wizard shows next to the configuration (no image is loaded)."""

    dataset_id: str
    version: str
    manifest_sha256: str
    num_images: int
    classes: list[str]
    class_counts: dict[str, int]
    split_counts: dict[str, int]
    split_strategy: str
    annotation_format: str
    synthetic: bool
    provenance: dict[str, Any]
    groups: int | None
    split_fingerprints: dict[str, str]


class DatasetResolver:
    """Resolves (dataset_id, version) through the independent catalogue (DatasetStore of the
    connector): same storage, same manifests, same caches — no parallel connector."""

    def __init__(self, store) -> None:
        self.store = store

    def families(self):
        return self.store.catalog()

    def manifest(self, dataset_id: str, version: str) -> tuple[str, dict]:
        return self.store.manifest(self.store.scope_id(dataset_id), version)

    def summary(self, dataset_id: str, version: str):
        idx = self.store.family_index(dataset_id)
        return next((v for v in idx.versions if v.version == version), None)

    def preview(self, dataset_id: str, version: str) -> DatasetPreview:
        sha, m = self.manifest(dataset_id, version)
        return preview_from_manifest(dataset_id, version, sha, m)


def preview_from_manifest(dataset_id: str, version: str, sha: str, m: dict) -> DatasetPreview:
    items = m.get("items", [])
    groups = {i.get("group") for i in items if i.get("group")}
    from mlops.databricks.datasets import split_fingerprints  # same fingerprint as the catalogue

    return DatasetPreview(
        dataset_id=dataset_id,
        version=version,
        manifest_sha256=sha,
        num_images=len(items),
        classes=list(m.get("classes") or sorted({i["label"] for i in items})),
        class_counts=dict(Counter(i["label"] for i in items)),
        split_counts={
            s: sum(1 for i in items if i["split"] == s) for s in ("train", "validation", "test")
        },
        split_strategy=m.get("split_strategy") or "random",
        annotation_format=m.get("annotation_format") or "classification",
        synthetic=bool(m.get("synthetic", False)),
        provenance={
            k: m[k]
            for k in (
                "generator",
                "seed",
                "parent_version",
                "created_at",
                "created_by",
                "description",
            )
            if m.get(k) is not None
        },
        groups=len(groups) if groups else None,
        split_fingerprints=m.get("split_fingerprints") or split_fingerprints(items),
    )


def effective_parameters(
    spec: PipelineSpec, overrides: dict[str, Any]
) -> tuple[dict[str, Any], list[Check]]:
    """Defaults of the pipeline + allowed overrides (typed, bounded). Imposed values are never
    overridden; unknown names are refused."""
    checks, values = [], {p.name: p.default for p in spec.parameters}
    for name, raw in (overrides or {}).items():
        p = spec.param(name)
        if p is None:
            checks.append(
                Check(
                    id=f"param:{name}",
                    label=f"Paramètre {name}",
                    status="error",
                    detail="non supporté par ce pipeline",
                )
            )
            continue
        if p.level == "imposed":
            if raw != p.default:
                checks.append(
                    Check(
                        id=f"param:{name}",
                        label=p.label,
                        status="error",
                        detail="imposé par l'intégration, non modifiable",
                    )
                )
            continue
        try:
            value = {"int": int, "float": float, "str": str, "bool": bool}[p.type](raw)
            if p.type == "int" and float(raw) != int(value):
                raise ValueError
        except (TypeError, ValueError):
            checks.append(
                Check(
                    id=f"param:{name}",
                    label=p.label,
                    status="error",
                    detail=f"type attendu : {p.type}",
                )
            )
            continue
        if (p.min is not None and value < p.min) or (p.max is not None and value > p.max):
            checks.append(
                Check(
                    id=f"param:{name}",
                    label=p.label,
                    status="error",
                    detail=f"hors bornes [{p.min} ; {p.max}]",
                )
            )
            continue
        values[name] = value
    if spec.parameters:
        changed = [p.label for p in spec.parameters if values[p.name] != p.default]
        checks.append(
            Check(
                id="params",
                label="Hyperparamètres",
                status="ok",
                detail=("modifiés : " + ", ".join(changed))
                if changed
                else "valeurs par défaut du pipeline",
            )
        )
    return values, checks


def dataset_checks(spec: PipelineSpec, dataset_id: str, m: dict) -> list[Check]:
    req, items = spec.dataset, m.get("items", [])
    out: list[Check] = []

    def add(cid: str, label: str, ok: bool, detail: str | None = None, warn: bool = False) -> None:
        out.append(
            Check(
                id=cid,
                label=label,
                status="ok" if ok else "warning" if warn else "error",
                detail=detail,
            )
        )

    fmt = m.get("annotation_format") or "classification"
    add(
        "format",
        "Format d'annotation",
        fmt == req.annotation_format,
        f"{fmt} (attendu : {req.annotation_format})",
    )
    classes = list(m.get("classes") or sorted({i["label"] for i in items}))
    add(
        "classes",
        "Classes",
        set(classes) == set(spec.classes),
        f"{', '.join(classes)} (attendu : {', '.join(spec.classes)})",
    )
    add(
        "family",
        "Famille de dataset",
        dataset_id in req.families,
        f"{dataset_id}"
        + (
            "" if dataset_id in req.families else f" — familles prévues : {', '.join(req.families)}"
        ),
        warn=True,
    )
    counts = Counter(i["split"] for i in items)
    missing = [s for s in req.required_splits if not counts.get(s)]
    add(
        "splits",
        "Splits disponibles",
        not missing,
        " / ".join(f"{s} {counts.get(s, 0)}" for s in ("train", "validation", "test"))
        + (f" — manquant : {', '.join(missing)}" if missing else ""),
    )
    bad_ext = [
        i["file"]
        for i in items
        if PurePosixPath(i["file"]).suffix.lower() not in req.image_extensions
    ]
    add(
        "extension",
        "Format des images",
        not bad_ext,
        f"{len(bad_ext)} fichier(s) hors {', '.join(req.image_extensions)}"
        if bad_ext
        else ", ".join(req.image_extensions),
    )
    bad_sha = [i["file"] for i in items if not SHA256.match(str(i.get("sha256", "")))]
    shas = [i.get("sha256") for i in items]
    add(
        "integrity",
        "Intégrité (SHA-256 par image)",
        not bad_sha and len(shas) == len(set(shas)),
        f"{len(bad_sha)} empreinte(s) invalide(s)"
        if bad_sha
        else "empreintes présentes et uniques"
        if len(shas) == len(set(shas))
        else "doublons d'images",
    )
    if req.group_field:
        no_group = [i["file"] for i in items if not i.get(req.group_field)]
        splits_of: dict[str, set[str]] = {}
        for i in items:
            if i.get(req.group_field):
                splits_of.setdefault(i[req.group_field], set()).add(i["split"])
        leaks = sorted(g for g, s in splits_of.items() if len(s) > 1)
        add(
            "groups",
            "Groupes (rafales) renseignés",
            not no_group or not req.group_required,
            f"{len(no_group)} image(s) sans rafale" if no_group else f"{len(splits_of)} rafales",
        )
        add(
            "leakage",
            "Aucune rafale dans plusieurs splits",
            not leaks,
            f"rafales à cheval : {', '.join(leaks[:5])}" if leaks else "contrôle par rafale réussi",
        )
    else:
        add(
            "leakage",
            "Contrôle de fuite par groupe",
            False,
            "le dataset ne déclare pas de groupes : contrôle impossible",
            warn=True,
        )
    return out


def blocking(checks: list[Check]) -> bool:
    return any(c.status == "error" for c in checks)
