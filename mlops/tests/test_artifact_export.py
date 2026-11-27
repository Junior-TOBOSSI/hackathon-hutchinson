"""Run artefacts: safe single downloads and a read-only zip export of the whole run."""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mlops.api import routes
from mlops.api.training_routes import safe_artifact, service_for
from mlops.tests.test_databricks_unit import connector  # noqa: F401 - shared fixture
from mlops.training import service as svc

FILES = {
    "evaluation/metriques.json": b'{"rappel": 0.85}',
    "evaluation/predictions.csv": b"fichier,verdict\nx.jpg,OK\n",
    "training/modele.onnx": b"onnx-bytes",
    "model/MLmodel": b"flavors: {}",
    "evaluation/annotated/a.jpg": b"jpeg-bytes",
    "notes/page.html": b"<script>alert(1)</script>",  # unknown type: never exported
}


@pytest.fixture
def api(connector, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(svc, "HOME", tmp_path)
    s = service_for(connector)
    monkeypatch.setattr(
        s, "artifacts", lambda rid: [{"path": p, "size": len(d)} for p, d in FILES.items()]
    )
    monkeypatch.setattr(s, "_artifact", lambda rid, p: FILES.get(p))
    app = FastAPI()
    app.include_router(routes.create_mlops_router(lambda: connector), prefix="/api")
    return TestClient(app)


def test_safe_artifact_paths():
    assert safe_artifact("evaluation/predictions.csv") and safe_artifact("model/MLmodel")
    for bad in ("../x.csv", "/etc/x.csv", "a/../../x.csv", "a\\x.csv", "x.html", "x.exe", ""):
        assert not safe_artifact(bad)


def test_single_download_inline_or_attachment(api):
    base = "/api/mlops/training/mlflow-runs/r1/artifact"
    r = api.get(base, params={"path": "evaluation/metriques.json"})
    assert r.status_code == 200 and r.headers["content-disposition"] == "inline"
    r = api.get(base, params={"path": "evaluation/metriques.json", "download": "true"})
    assert r.headers["content-disposition"].startswith("attachment")
    r = api.get(base, params={"path": "training/modele.onnx"})
    assert r.headers["content-disposition"].startswith("attachment")
    assert api.get(base, params={"path": "notes/page.html"}).status_code == 400


def test_zip_export_contains_every_safe_artifact_and_lists_the_others(api, connector):  # noqa: F811
    r = api.get("/api/mlops/training/mlflow-runs/r1abcdefgh/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert 'filename="run-r1abcdef-artifacts.zip"' in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"evaluation/predictions.csv", "training/modele.onnx", "model/MLmodel"} <= names
    assert z.read("evaluation/annotated/a.jpg") == b"jpeg-bytes"
    assert "notes/page.html" not in names
    assert "notes/page.html" in z.read("NOT_EXPORTED.txt").decode()
    connector.w.jobs.run_now.assert_not_called()  # read-only
