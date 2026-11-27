"""MLflow packaging of the Quality model: the group's ``Qualite702`` class does ALL the
inference (pre-processing, model, post-processing, threshold); nothing is re-implemented.

Unity Catalog requires a signature: input = one image path per row; output = the group's
main fields plus its complete JSON answer, unchanged, in ``resultat_json``.
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    from mlflow.pyfunc import PythonModel
except ImportError:  # local tooling without mlflow
    PythonModel = object

OUTPUT_COLUMNS = [
    ("verdict", "string"),
    ("type_defaut", "string"),
    ("score_nok", "double"),
    ("latence_ms", "double"),
    ("resultat_json", "string"),
]


class Qualite702Model(PythonModel):
    def load_context(self, context):
        from qualite702 import Qualite702

        self.model = Qualite702(context.artifacts["config"], device="cpu")

    def predict(self, context, model_input, params=None):
        import pandas as pd

        rows = []
        for path in model_input["path"]:
            r = self.model.predire(str(path))
            rows.append(
                {
                    "verdict": r["verdict"],
                    "type_defaut": r["type_defaut"] or "",
                    "score_nok": float(r["score_nok"]),
                    "latence_ms": float(r["latence_ms"]),
                    "resultat_json": json.dumps(r, ensure_ascii=False),
                }
            )
        return pd.DataFrame(rows, columns=[c for c, _ in OUTPUT_COLUMNS])


def signature():
    from mlflow.models import ModelSignature
    from mlflow.types import ColSpec, Schema

    return ModelSignature(
        inputs=Schema([ColSpec("string", "path")]),
        outputs=Schema([ColSpec(t, c) for c, t in OUTPUT_COLUMNS]),
    )


def log_quality_model(mlflow, model_dir: Path, kit: Path):
    return mlflow.pyfunc.log_model(
        name="model",
        python_model=Qualite702Model(),
        artifacts={
            "config": str(model_dir / "config_qualite702.yaml"),
            "weights": str(model_dir / "modele.pt"),
        },
        code_paths=[str(kit / "qualite702")],
        signature=signature(),
        pip_requirements=["ultralytics==8.4.219", "pyyaml", "numpy", "pillow", "pandas"],
    )
