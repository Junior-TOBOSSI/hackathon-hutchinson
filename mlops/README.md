# ARGOS MLOps (BUILD)

Périmètre du groupe ARGOS MLOps : versionnement des données, entraînement et évaluation, suivi des expériences et registre des modèles (**MLflow, source de vérité**), livraison des modèles aux postes, monitoring et réentraînement. Databricks reste une cible à confirmer (les contrats acceptent déjà les noms Unity Catalog `catalog.schema.model`, rien n'est testé sur Databricks).

## État : MLOPS-01 Foundation

| Fait | Pas encore (chantiers suivants) |
|---|---|
| Serveur MLflow 3.18.0 local (SQLite + artefacts locaux servis par le serveur) | DVC, datasets industriels |
| Expérience pédagogique `argos-foundation-demo` : 4 vrais entraînements CPU sur données **synthétiques** | Training Factory des 3 modèles IA, GPU |
| Artefacts, Logged Models, Model Registry `argos-foundation-demo-model`, alias `champion` / `challenger` | Evaluation Gate, export ONNX, `model-package.json` produit par pipeline |
| Connecteur Python ARGOS → MLflow (`mlops/connectors`) | API FastAPI définitive, écrans AI Leader |
| Tests unitaires (mocks) et d'intégration (serveur réel) | Déploiement Edge, monitoring, drift, réentraînement |

**Toutes les données, expériences et modèles de MLOPS-01 sont synthétiques (`synthetic=true`) : ce ne sont pas des modèles industriels.** Une promotion d'alias dans MLflow n'est **jamais** un déploiement sur un poste Edge.

## Documentation

- [docs/foundation.md](docs/foundation.md) — comprendre : architecture client-serveur, stores, URI, Experiment / Run / Logged Model / Registered Model / Version / Alias, chemin d'une requête et d'un artefact, connecteur, intégration future FastAPI + React, local vs industriel.
- [docs/exploration-guide.md](docs/exploration-guide.md) — manipuler : parcours pas à pas (UI, connecteur, SQLite en lecture seule, stockage physique).
- [../docs/integration-contracts.md](../docs/integration-contracts.md#4-contrats-mlops-groupe-argos-mlops) — contrats MLOps ARGOS (`visionhub/integration/mlops.py`).

## Démarrage rapide (PowerShell, depuis la racine du dépôt)

```powershell
$mlops = "$env:USERPROFILE\ARGOS_MLOPS_LOCAL"            # ou $env:ARGOS_MLOPS_HOME
$py = "$mlops\.venv\Scripts\python.exe"

powershell -ExecutionPolicy Bypass -File mlops\scripts\start_mlflow.ps1   # http://127.0.0.1:5000
powershell -ExecutionPolicy Bypass -File mlops\scripts\check_mlflow.ps1   # 9 vérifications
& $py -m mlops.scripts.seed_demo                                          # idempotent
& $py -m mlops.scripts.inspect_mlflow resolve models:/argos-foundation-demo-model@champion
& $py -m mlops.scripts.predict_registered
powershell -ExecutionPolicy Bypass -File mlops\scripts\stop_mlflow.ps1    # les données restent
```

## Organisation

```text
mlops/
  config.py                 configuration par variables d'environnement (aucune URI codée en dur ailleurs)
  connectors/
    mlflow_client.py        ArgosMlflowConnector : lecture tracking/registry, alias de démo
    errors.py               erreurs explicites (serveur indisponible, inconnu, téléchargement…)
  demo/
    data.py                 dataset synthétique make_classification + split fixe 60/20/20
    training.py             4 configurations, entraînements réels, historiques réels
  scripts/
    start_mlflow.ps1  stop_mlflow.ps1  check_mlflow.ps1
    seed_demo.py            expérience + runs + artefacts + registry + alias
    inspect_mlflow.py       explorer MLflow via le connecteur (sortie JSON)
    predict_registered.py   charger models:/… et prédire
    demo_metric_history.py  courbe SIMULÉE (expérience séparée) pour expliquer step=
    inspect_sqlite.py       lecture SEULE de la base, à but pédagogique
  tests/                    unitaires (mocks) + intégration (ARGOS_MLFLOW_IT=1)
  examples/                 exemples de contrats (générés par l'Intégration)
  requirements.txt          dépendances directes ; requirements-lock.txt = gel complet
```

## Environnement

Environnement isolé, **hors du dépôt** : `%USERPROFILE%\ARGOS_MLOPS_LOCAL\` (`.venv`, `storage\mlflow.db`, `storage\mlartifacts\`, `logs\`, `downloads\`). Les dépendances MLOps ne sont jamais installées dans l'environnement principal ARGOS ; le package ARGOS y est installé en mode éditable (`pip install -e .`) uniquement pour réutiliser les contrats (`ModelRef`…).

```powershell
& $py -m pip install -r mlops\requirements.txt; & $py -m pip install -e .; & $py -m pip check
```

## Tests

```powershell
& $py -m pytest mlops/tests                              # unitaires (aucun serveur requis)
$env:ARGOS_MLFLOW_IT = "1"; & $py -m pytest mlops/tests  # + intégration contre le serveur local
```

Les tests d'intégration utilisent leur propre expérience et leur propre modèle (suffixe aléatoire) et les suppriment à la fin : les données de démonstration ne sont jamais touchées. Ils ne sont pas collectés par la CI historique (`testpaths = tests, usecases`).

## Règles

- Données Hutchinson : jamais dans Git, jamais dans l'expérience de démonstration, jamais vers un service externe.
- Le stockage MLflow (base SQLite, artefacts, modèles) reste hors du dépôt.
- Le connecteur n'écrit dans le Registry que pour les modèles `argos-foundation-demo*`.
- Ne pas modifier `visionhub/integration/mlops.py` sans PR relue par l'Intégration.
