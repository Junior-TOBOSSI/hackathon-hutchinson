"""Quality decision metrics computed from the group's predictions.csv (binary and 3 classes)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mlops.connectors.mlflow_client import RunSummary
from mlops.pipelines.quality_industrial.decision_metrics import (
    decision_metrics,
    mlflow_test_metrics,
    rows_from_csv,
)
from mlops.training.service import TrainingService, confusion


def row(truth: str, verdict: str, kind: str = "") -> dict[str, str]:
    return {
        "fichier": "x.jpg",
        "vraie_classe": truth,
        "vrai": "OK" if truth == "OK" else "NOK",
        "verdict": verdict,
        "type_defaut": kind if verdict == "NOK" else "",
        "score_nok": "0.5",
        "latence_ms": "3",
    }


# binary: 6 NOK (4 stopped, 1 declared OK, 1 to review), 10 OK (7 OK, 2 rejected, 1 to review)
BINARY = (
    [row("NOK", "NOK", "NOK")] * 4
    + [row("NOK", "OK")]
    + [row("NOK", "A_VERIFIER")]
    + [row("OK", "OK")] * 7
    + [row("OK", "NOK", "NOK")] * 2
    + [row("OK", "A_VERIFIER")]
)


def group_rates(rows):
    """Formulas of the group's evaluer.py (metriques.json), copied for the consistency check."""
    nok = [r for r in rows if r["vrai"] == "NOK"]
    ok = [r for r in rows if r["vrai"] == "OK"]
    stopped = sum(r["verdict"] == "NOK" for r in nok)
    doubt = sum(r["verdict"] == "A_VERIFIER" for r in nok)
    return {
        "rappel": stopped / len(nok),
        "nok_declarees_ok": (len(nok) - stopped - doubt) / len(nok),
        "faux_rejets": sum(r["verdict"] == "NOK" for r in ok) / len(ok),
        "a_verifier_ok": sum(r["verdict"] == "A_VERIFIER" for r in ok) / len(ok),
    }


def test_binary_counts_and_metrics():
    m = decision_metrics(BINARY)
    assert (m["tp"], m["fn"], m["a_verifier_nok"]) == (4, 1, 1)
    assert (m["tn"], m["fp"], m["a_verifier_ok"]) == (7, 2, 1)
    assert m["n"] == 16 == m["tp"] + m["tn"] + m["fp"] + m["fn"] + 2
    assert m["accuracy"] == pytest.approx(11 / 16)  # A_VERIFIER is never counted as correct
    assert m["precision_nok"] == pytest.approx(4 / 6)
    assert m["recall_nok"] == pytest.approx(4 / 6)
    assert m["f1_nok"] == pytest.approx(2 * (4 / 6) * (4 / 6) / (8 / 6))
    assert m["false_reject_rate"] == pytest.approx(2 / 10)
    assert m["a_verifier_rate"] == pytest.approx(2 / 16)
    # binary kit: class accuracy == decision accuracy, per-class NOK == global NOK metrics
    assert m["accuracy_class"] == pytest.approx(m["accuracy"])
    assert m["per_class"]["NOK"]["recall"] == pytest.approx(m["recall_nok"])
    assert m["per_class"]["NOK"]["precision"] == pytest.approx(m["precision_nok"])


def test_consistent_with_the_group_rates_and_the_confusion_matrix():
    m, g = decision_metrics(BINARY), group_rates(BINARY)
    assert m["recall_nok"] == pytest.approx(g["rappel"])
    assert m["false_reject_rate"] == pytest.approx(g["faux_rejets"])
    assert m["fn"] / m["n_nok"] == pytest.approx(g["nok_declarees_ok"])
    assert m["a_verifier_ok"] / m["n_ok"] == pytest.approx(g["a_verifier_ok"])
    cm = confusion(BINARY)  # matrix shown by Training Factory
    assert cm["matrix"]["NOK"] == {"OK": 1, "A_VERIFIER": 1, "NOK": 4}
    assert cm["matrix"]["OK"] == {"OK": 7, "A_VERIFIER": 1, "NOK": 2}
    for c in ("OK", "NOK"):
        for k in ("precision", "recall", "f1"):
            assert cm["per_class"][c][k] == pytest.approx(m["per_class"][c][k])


def test_three_classes_binary_decision_and_type_level():
    rows = (
        [row("NOK_absent", "NOK", "NOK_absent")] * 3
        + [row("NOK_absent", "NOK", "NOK_double")]  # stopped, wrong type
        + [row("NOK_double", "NOK", "NOK_double")] * 2
        + [row("NOK_double", "A_VERIFIER")]
        + [row("OK", "OK")] * 5
        + [row("OK", "NOK", "NOK_absent")]
    )
    m = decision_metrics(rows)
    assert (m["tp"], m["fn"], m["a_verifier_nok"], m["tn"], m["fp"]) == (6, 0, 1, 5, 1)
    assert m["accuracy"] == pytest.approx(11 / 13)
    assert m["accuracy_class"] == pytest.approx(10 / 13)  # the type confusion is not "correct"
    assert m["precision_nok"] == pytest.approx(6 / 7) and m["recall_nok"] == pytest.approx(6 / 7)
    assert m["per_class"]["NOK_absent"]["recall"] == pytest.approx(3 / 4)
    assert m["per_class"]["NOK_absent"]["precision"] == pytest.approx(3 / 4)
    assert m["per_class"]["NOK_double"]["recall"] == pytest.approx(2 / 3)
    assert m["recall_nok"] == pytest.approx(group_rates(rows)["rappel"])
    cm = confusion(rows)
    for c in ("OK", "NOK_absent", "NOK_double"):
        assert cm["per_class"][c]["recall"] == pytest.approx(m["per_class"][c]["recall"])


def test_mlflow_keys_and_unknown_verdict():
    out = mlflow_test_metrics(BINARY)
    for k in ("test_accuracy", "test_precision_nok", "test_recall_nok", "test_f1_nok",
              "test_false_reject_rate", "test_tp", "test_tn", "test_fp", "test_fn",
              "test_class_NOK_f1"):  # fmt: skip
        assert k in out
    assert all(isinstance(v, float) for v in out.values())
    no_nok_predicted = [row("OK", "OK"), row("NOK", "OK")]
    assert "test_precision_nok" not in mlflow_test_metrics(no_nok_predicted)  # None: not logged
    with pytest.raises(ValueError):
        decision_metrics([row("OK", "MAYBE")])


def csv_bytes(rows):
    head = list(rows[0])
    lines = [",".join(head)] + [",".join(r[k] for k in head) for r in rows]
    return ("\n".join(lines) + "\n").encode()


def summary(metrics, tags, status="FINISHED"):
    return RunSummary(
        run_id="r1", run_name="x", experiment_id="1", status=status, start_time=None,
        end_time=None, artifact_uri="dbfs:/x", params={}, metrics=metrics, tags=tags,
    )  # fmt: skip


@pytest.fixture
def service():
    svc = TrainingService.__new__(TrainingService)
    svc.reads = []
    svc._artifact = lambda run_id, path: svc.reads.append(path) or csv_bytes(BINARY)
    return svc


QUALITY = {"hovis.pipeline": "quality-industrial-binary", "hovis.evaluation_split": "test"}


def test_historical_run_gets_derived_metrics_without_mutation(service):
    run = summary({"test_rappel": 4 / 6, "test_faux_rejets": 0.2}, dict(QUALITY))
    out = service.with_decision_metrics(run)
    assert out.metrics["test_accuracy"] == pytest.approx(11 / 16)
    assert out.metrics["test_f1_nok"] == pytest.approx(4 / 6)
    assert out.metrics["test_rappel"] == run.metrics["test_rappel"]  # logged values kept
    assert out.tags["hovis.metrics_derived_from"] == "evaluation/predictions.csv"
    assert "test_accuracy" not in run.metrics and "hovis.metrics_derived_from" not in run.tags
    assert service.reads == ["evaluation/predictions.csv"]
    assert out.metrics["test_recall_nok"] == pytest.approx(out.metrics["test_rappel"])


def test_other_runs_are_returned_unchanged(service):
    for run in (
        summary({"test_accuracy": 0.9}, dict(QUALITY)),  # new run: logged metrics only
        summary({}, {"hovis.pipeline": "workstation-industrial"}),
        summary({}, dict(QUALITY), status="RUNNING"),
    ):
        assert service.with_decision_metrics(run) is run
    assert service.reads == []
    svc = SimpleNamespace(_artifact=lambda *a: None)
    run = summary({}, dict(QUALITY))
    assert TrainingService.with_decision_metrics(svc, run) is run  # no artefact: unchanged


def test_rows_from_csv_roundtrip():
    assert decision_metrics(rows_from_csv(csv_bytes(BINARY)))["tp"] == 4
