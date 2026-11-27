"""Load a REGISTERED model by URI and predict on synthetic samples.

    python -m mlops.scripts.predict_registered                 # models:/...@champion
    python -m mlops.scripts.predict_registered --model-uri URI
        URI = models:/argos-foundation-demo-model/2
           or models:/argos-foundation-demo-model@challenger

The URI is first resolved by the ARGOS connector (which version, which run, which Logged
Model), then loaded with ``mlflow.pyfunc``: the generic loader that any ARGOS service can
use without knowing the model library. Loading a model in MLflow is NOT deploying it to an
Edge station.
"""

from __future__ import annotations

import argparse
import sys

import mlflow
import mlflow.pyfunc
import numpy as np

from mlops.config import DEMO_MODEL, MlflowSettings, utf8_console
from mlops.connectors import ArgosMlflowConnector
from mlops.demo.data import CLASSES, make_dataset


def main(argv: list[str] | None = None) -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-uri", default=f"models:/{DEMO_MODEL}@champion")
    parser.add_argument("--samples", type=int, default=10)
    args = parser.parse_args(argv)

    settings = MlflowSettings.from_env()
    connector = ArgosMlflowConnector(settings)
    version = connector.resolve(args.model_uri)
    print(f"{args.model_uri} -> version {version.version} (aliases {version.aliases})")
    print(f"  run_id   : {version.run_id}")
    print(f"  model_id : {version.model_id}")
    print(f"  source   : {version.source}")

    mlflow.set_tracking_uri(settings.tracking_uri)
    mlflow.set_registry_uri(settings.registry_uri)
    model = mlflow.pyfunc.load_model(args.model_uri)

    # Synthetic samples from the held-out split (inference demo, not a model selection).
    data = make_dataset()
    X, y = data.X_test.head(args.samples), data.y_test[: args.samples]
    predictions = np.asarray(model.predict(X))
    for index, (truth, predicted) in enumerate(zip(y, predictions, strict=True)):
        mark = "ok " if truth == predicted else "ERR"
        print(
            f"  sample {index:02d}: predicted {CLASSES[predicted]:<8} "
            f"expected {CLASSES[truth]:<8} {mark}"
        )
    print(f"Accuracy on these {len(y)} synthetic samples: {(predictions == y).mean():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
