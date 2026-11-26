"""Reproducible SYNTHETIC classification dataset with a fixed train/validation/test split.

- 3 000 samples, 20 features (8 informative, 4 redundant), 3 classes, 2 % label noise.
- Stratified split 60 % / 20 % / 20 % (1 800 / 600 / 600), random_state = 42.
- Validation is used to compare and SELECT models; test is only used AFTER the selection.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split

DATASET_NAME = "argos-synthetic-classification"
DATASET_SEED = 42
GENERATOR_PARAMS: dict[str, Any] = {
    "n_samples": 3000,
    "n_features": 20,
    "n_informative": 8,
    "n_redundant": 4,
    "n_classes": 3,
    "n_clusters_per_class": 2,
    "class_sep": 1.0,
    "flip_y": 0.02,
}
SPLIT = {"train": 0.6, "validation": 0.2, "test": 0.2}
FEATURES = [f"f{i:02d}" for i in range(GENERATOR_PARAMS["n_features"])]
CLASSES = [f"class_{i}" for i in range(GENERATOR_PARAMS["n_classes"])]


@dataclass(frozen=True)
class SyntheticDataset:
    X_train: pd.DataFrame
    X_val: pd.DataFrame
    X_test: pd.DataFrame
    y_train: np.ndarray
    y_val: np.ndarray
    y_test: np.ndarray
    info: dict[str, Any]

    def frame(self, split: str) -> pd.DataFrame:
        """Features + ``label`` column, for MLflow dataset inputs."""
        X, y = {
            "train": (self.X_train, self.y_train),
            "validation": (self.X_val, self.y_val),
            "test": (self.X_test, self.y_test),
        }[split]
        return X.assign(label=y)


def make_dataset(seed: int = DATASET_SEED) -> SyntheticDataset:
    X, y = make_classification(**GENERATOR_PARAMS, random_state=seed)
    X = pd.DataFrame(X, columns=FEATURES)
    X_rest, X_test, y_rest, y_test = train_test_split(
        X, y, test_size=SPLIT["test"], stratify=y, random_state=seed
    )
    val_share = SPLIT["validation"] / (SPLIT["train"] + SPLIT["validation"])
    X_train, X_val, y_train, y_val = train_test_split(
        X_rest, y_rest, test_size=val_share, stratify=y_rest, random_state=seed
    )
    info = {
        "name": DATASET_NAME,
        "synthetic": True,
        "generator": "sklearn.datasets.make_classification",
        "generator_params": GENERATOR_PARAMS,
        "seed": seed,
        "features": FEATURES,
        "classes": CLASSES,
        "split_strategy": "stratified random, fixed seed",
        "split_ratios": SPLIT,
        "split_sizes": {"train": len(y_train), "validation": len(y_val), "test": len(y_test)},
        "class_counts": {
            name: np.bincount(labels, minlength=len(CLASSES)).tolist()
            for name, labels in (("train", y_train), ("validation", y_val), ("test", y_test))
        },
        "sha256": hashlib.sha256(np.ascontiguousarray(X.to_numpy()).tobytes()).hexdigest(),
    }
    return SyntheticDataset(X_train, X_val, X_test, y_train, y_val, y_test, info)
