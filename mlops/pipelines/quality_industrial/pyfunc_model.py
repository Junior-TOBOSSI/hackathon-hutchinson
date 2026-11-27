"""MLflow packaging of the Quality model: the group's ``Qualite702`` class does ALL the
inference (pre-processing, model, post-processing, threshold); nothing is re-implemented."""

from __future__ import annotations

from pathlib import Path

try:
    from mlflow.pyfunc import PythonModel
except ImportError:  # local tooling without mlflow
    PythonModel = object


class Qualite702Model(PythonModel):
    def load_context(self, context):
        from qualite702 import Qualite702

        self.model = Qualite702(context.artifacts["config"], device="cpu")

    def predict(self, context, model_input, params=None):
        """``model_input``: DataFrame with a ``path`` column (image files) -> group's JSON."""
        return [self.model.predire(str(p)) for p in model_input["path"]]


def log_quality_model(mlflow, model_dir: Path, kit: Path):
    return mlflow.pyfunc.log_model(
        name="model",
        python_model=Qualite702Model(),
        artifacts={
            "config": str(model_dir / "config_qualite702.yaml"),
            "weights": str(model_dir / "modele.pt"),
        },
        code_paths=[str(kit / "qualite702")],
        pip_requirements=["ultralytics==8.4.219", "pyyaml", "numpy", "pillow"],
    )
