"""Real CPU trainings of small scikit-learn classifiers, with REAL metric histories.

Each model family gives a genuine per-step history:
- SGD logistic regression: one step = one epoch of ``partial_fit``;
- random forest: one step = number of trees (``warm_start`` adds trees);
- gradient boosting: one step = boosting stage (``staged_predict_proba``, ``train_score_``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.base import BaseEstimator
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from mlops.demo.data import CLASSES, SyntheticDataset

TRAINING_CONFIGS: list[dict[str, Any]] = [
    {
        "run_name": "sgd-logistic-a",
        "family": "sgd",
        "architecture": "StandardScaler + SGDClassifier(loss=log_loss)",
        "seed": 7,
        "hyperparameters": {"alpha": 1e-4, "epochs": 30, "learning_rate": "optimal"},
    },
    {
        "run_name": "random-forest-b",
        "family": "random_forest",
        "architecture": "RandomForestClassifier",
        "seed": 7,
        "hyperparameters": {"n_estimators": 200, "max_depth": 8, "trees_per_step": 20},
    },
    {
        "run_name": "random-forest-c",
        "family": "random_forest",
        "architecture": "RandomForestClassifier",
        "seed": 7,
        "hyperparameters": {
            "n_estimators": 300,
            "max_depth": None,
            "min_samples_leaf": 2,
            "trees_per_step": 30,
        },
    },
    {
        "run_name": "gradient-boosting-d",
        "family": "gradient_boosting",
        "architecture": "GradientBoostingClassifier",
        "seed": 7,
        "hyperparameters": {"n_estimators": 150, "learning_rate": 0.1, "max_depth": 3},
    },
]


@dataclass
class TrainingResult:
    model: BaseEstimator
    train_time_s: float
    history: dict[str, list[tuple[int, float]]] = field(default_factory=dict)


def train(config: dict[str, Any], data: SyntheticDataset) -> TrainingResult:
    trainer = {"sgd": _sgd, "random_forest": _random_forest, "gradient_boosting": _boosting}
    start = time.perf_counter()
    model, history = trainer[config["family"]](config["hyperparameters"], config["seed"], data)
    return TrainingResult(model, time.perf_counter() - start, history)


def _sgd(hp: dict, seed: int, data: SyntheticDataset):
    scaler = StandardScaler().fit(data.X_train)
    X_train, X_val = scaler.transform(data.X_train), scaler.transform(data.X_val)
    sgd = SGDClassifier(
        loss="log_loss", alpha=hp["alpha"], learning_rate=hp["learning_rate"], random_state=seed
    )
    rng = np.random.default_rng(seed)
    classes = np.arange(len(CLASSES))
    history: dict[str, list[tuple[int, float]]] = {
        "train_log_loss": [],
        "val_log_loss": [],
        "val_accuracy": [],
    }
    for epoch in range(1, hp["epochs"] + 1):
        order = rng.permutation(len(X_train))
        sgd.partial_fit(X_train[order], data.y_train[order], classes=classes)
        history["train_log_loss"].append(
            (epoch, log_loss(data.y_train, sgd.predict_proba(X_train), labels=classes))
        )
        history["val_log_loss"].append(
            (epoch, log_loss(data.y_val, sgd.predict_proba(X_val), labels=classes))
        )
        history["val_accuracy"].append((epoch, accuracy_score(data.y_val, sgd.predict(X_val))))
    # Both steps are already fitted: the pipeline is only used to predict on raw features.
    return Pipeline([("scaler", scaler), ("classifier", sgd)]), history


def _random_forest(hp: dict, seed: int, data: SyntheticDataset):
    params = {k: v for k, v in hp.items() if k not in ("n_estimators", "trees_per_step")}
    forest = RandomForestClassifier(
        n_estimators=0, warm_start=True, random_state=seed, n_jobs=1, **params
    )
    history: dict[str, list[tuple[int, float]]] = {"val_accuracy": []}
    for n_trees in range(hp["trees_per_step"], hp["n_estimators"] + 1, hp["trees_per_step"]):
        forest.set_params(n_estimators=n_trees)
        forest.fit(data.X_train, data.y_train)
        history["val_accuracy"].append(
            (n_trees, accuracy_score(data.y_val, forest.predict(data.X_val)))
        )
    forest.set_params(warm_start=False)
    return forest, history


def _boosting(hp: dict, seed: int, data: SyntheticDataset):
    booster = GradientBoostingClassifier(random_state=seed, **hp).fit(data.X_train, data.y_train)
    classes = np.arange(len(CLASSES))
    history: dict[str, list[tuple[int, float]]] = {
        "train_loss": [],
        "val_log_loss": [],
        "val_accuracy": [],
    }
    for stage, proba in enumerate(booster.staged_predict_proba(data.X_val), start=1):
        history["val_log_loss"].append((stage, log_loss(data.y_val, proba, labels=classes)))
        history["val_accuracy"].append((stage, accuracy_score(data.y_val, proba.argmax(axis=1))))
    history["train_loss"] = [(i, float(v)) for i, v in enumerate(booster.train_score_, start=1)]
    return booster, history


def evaluate(
    model: BaseEstimator, X, y, prefix: str
) -> tuple[dict[str, float], dict, list[list[int]]]:
    """Global and per-class metrics, the full report and the confusion matrix."""
    predictions = model.predict(X)
    report = classification_report(
        y,
        predictions,
        labels=list(range(len(CLASSES))),
        target_names=CLASSES,
        output_dict=True,
        zero_division=0,
    )
    metrics = {
        f"{prefix}_accuracy": accuracy_score(y, predictions),
        f"{prefix}_precision_macro": precision_score(
            y, predictions, average="macro", zero_division=0
        ),
        f"{prefix}_recall_macro": recall_score(y, predictions, average="macro", zero_division=0),
        f"{prefix}_f1_macro": f1_score(y, predictions, average="macro", zero_division=0),
    }
    for name in CLASSES:
        for measure in ("precision", "recall", "f1-score"):
            metrics[f"{prefix}_{measure.replace('-score', '')}_{name}"] = report[name][measure]
    matrix = confusion_matrix(y, predictions, labels=list(range(len(CLASSES)))).tolist()
    return {k: float(v) for k, v in metrics.items()}, report, matrix
