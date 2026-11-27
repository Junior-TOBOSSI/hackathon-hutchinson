"""Test metrics computed from the REAL predictions of the group's evaluer.py (predictions.csv).

The group's evaluer.py writes one row per test photo (vraie_classe, vrai, verdict, type_defaut,
score_nok) and only a few aggregated rates in metriques.json (rappel, faux_rejets, ...). This
module derives the missing standard metrics from those rows. It never re-runs a model, never
changes a threshold: it only counts the verdicts that the group's code already produced.

Conventions (positive class = NOK, consistent with the group's metriques.json):

- predicted NOK  <=> verdict == "NOK"; predicted OK <=> verdict == "OK".
- verdict "A_VERIFIER" (human review) is NEVER counted as a correct prediction. It is counted
  apart (``a_verifier_nok`` / ``a_verifier_ok``) and kept in every denominator, so:
    TP = NOK -> NOK      FN = NOK -> OK          a_verifier_nok = NOK -> A_VERIFIER
    TN = OK  -> OK       FP = OK  -> NOK         a_verifier_ok  = OK  -> A_VERIFIER
    n = TP + FN + a_verifier_nok + TN + FP + a_verifier_ok
- accuracy        = (TP + TN) / n                  (binary OK / NOK decision)
- precision_nok   = TP / (TP + FP)
- recall_nok      = TP / n_NOK                     (== group's "rappel")
- f1_nok          = 2 * P * R / (P + R)
- false_reject_rate = FP / n_OK                    (== group's "faux_rejets")
- per class (OK, NOK or NOK types for the three-class kit): predicted class = OK / A_VERIFIER /
  ``type_defaut`` (same columns as the group's confusion matrix); precision, recall, F1 per class
  and ``accuracy_class`` = diagonal / n. For the binary kit, accuracy_class == accuracy.

Standard library only: it runs inside the Databricks job and in the HOVIS gateway.
"""

from __future__ import annotations

import csv
import io
from typing import Any

REVIEW = "A_VERIFIER"


def predicted_class(row: dict[str, str]) -> str:
    """Column of the group's confusion matrix: OK / A_VERIFIER / predicted NOK type."""
    verdict = row["verdict"]
    if verdict in ("OK", REVIEW):
        return verdict
    return row.get("type_defaut") or "NOK"


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None:
        return None
    return 2 * p * r / (p + r) if (p + r) else 0.0


def decision_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Confusion counts, global metrics and per-class metrics from predictions.csv rows."""
    tp = tn = fp = fn = av_nok = av_ok = 0
    for r in rows:
        truth_nok = (r.get("vrai") or ("OK" if r["vraie_classe"] == "OK" else "NOK")) == "NOK"
        verdict = r["verdict"]
        if verdict not in ("OK", "NOK", REVIEW):
            raise ValueError(f"unknown verdict {verdict!r} in predictions.csv")
        if truth_nok:
            tp += verdict == "NOK"
            fn += verdict == "OK"
            av_nok += verdict == REVIEW
        else:
            tn += verdict == "OK"
            fp += verdict == "NOK"
            av_ok += verdict == REVIEW
    n_nok, n_ok = tp + fn + av_nok, tn + fp + av_ok
    n = n_nok + n_ok
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, n_nok)

    truths = sorted({r["vraie_classe"] for r in rows}, key=lambda c: (c != "OK", c))
    per_class: dict[str, dict[str, float | int | None]] = {}
    diagonal = 0
    for c in truths:
        support = sum(r["vraie_classe"] == c for r in rows)
        predicted = sum(predicted_class(r) == c for r in rows)
        hit = sum(r["vraie_classe"] == c and predicted_class(r) == c for r in rows)
        diagonal += hit
        p_c, r_c = _ratio(hit, predicted), _ratio(hit, support)
        per_class[c] = {"support": support, "precision": p_c, "recall": r_c, "f1": _f1(p_c, r_c)}

    return {
        "n": n,
        "n_nok": n_nok,
        "n_ok": n_ok,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "a_verifier_nok": av_nok,
        "a_verifier_ok": av_ok,
        "accuracy": _ratio(tp + tn, n),
        "accuracy_class": _ratio(diagonal, n),
        "precision_nok": precision,
        "recall_nok": recall,
        "f1_nok": _f1(precision, recall),
        "false_reject_rate": _ratio(fp, n_ok),
        "a_verifier_rate": _ratio(av_nok + av_ok, n),
        "per_class": per_class,
    }


def mlflow_test_metrics(rows: list[dict[str, str]]) -> dict[str, float]:
    """Flat ``test_*`` MLflow metrics (None values are left out, never logged as 0)."""
    m = decision_metrics(rows)
    out: dict[str, float] = {}
    for key in (
        "tp", "tn", "fp", "fn", "a_verifier_nok", "a_verifier_ok", "accuracy", "accuracy_class",
        "precision_nok", "recall_nok", "f1_nok", "false_reject_rate", "a_verifier_rate",
    ):  # fmt: skip
        if m[key] is not None:
            out[f"test_{key}"] = float(m[key])
    for c, v in m["per_class"].items():
        for key in ("precision", "recall", "f1"):
            if v[key] is not None:
                out[f"test_class_{c}_{key}"] = float(v[key])
    return out


def rows_from_csv(data: bytes | str) -> list[dict[str, str]]:
    text = data.decode("utf-8") if isinstance(data, bytes) else data
    return list(csv.DictReader(io.StringIO(text)))
