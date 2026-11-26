# ARGOS MLOps (BUILD)

Périmètre du groupe ARGOS MLOps : versionnement des données (DVC), entraînement et évaluation (cluster A100), suivi des expériences et registre des modèles (**MLflow, source de vérité**), export ONNX, livraison des modèles aux postes, monitoring des dérives et politique de réentraînement. Databricks (Unity Catalog, Jobs) est une cible à confirmer : les contrats acceptent déjà les noms `catalog.schema.model`.

**État : à construire par le groupe.** Rien n'est installé ici : ni MLflow, ni DVC, ni Databricks.

## Contrats à respecter

Définis dans `visionhub/integration/mlops.py` et expliqués dans [docs/integration-contracts.md](../docs/integration-contracts.md#4-contrats-mlops-groupe-argos-mlops) :

| Contrat | Usage |
|---|---|
| `DatasetRef` | version DVC d'un jeu de données (jamais les données elles-mêmes dans Git) |
| `TrainingConfig`, `TrainingJob` | lancement et suivi d'un entraînement (lié à un run MLflow) |
| `EvaluationMetrics` | métriques loguées dans MLflow et reprises par l'AI Leader |
| `ModelRef` | nom et version MLflow (`models:/<nom>/<version>`) |
| `ModelPackage` | **livrable vers l'Edge** : `model-package.json` (exemple : `examples/model-package.example.json`) |
| `ModelDeployment`, `StationDeploymentStatus` | déploiement demandé et version réellement chargée par poste |
| `MonitoringMetrics`, `DriftMeasure` | dérive des données et concordance humain / IA |
| `RetrainingPolicy` | réentraînement automatique possible, **déploiement toujours approuvé** |

Vérification d'un paquet produit par vos pipelines :

```python
from visionhub.integration.mlops import ModelPackage
ModelPackage.model_validate_json(open("model-package.json", encoding="utf-8").read())
```

## Règles

- Données Hutchinson : jamais dans Git, jamais vers un service externe non autorisé ; vérifier les autorisations avant tout transfert vers le cluster.
- Split du dataset qualité **par séquence d'acquisition**.
- Poids entraînés sur données confidentielles : jamais dans Git (`.gitignore` couvre `*.pt`, `*.onnx`, `mlruns/`, `mlartifacts/`, cache DVC).
- Ne pas modifier `visionhub/integration/mlops.py` sans PR relue par l'Intégration.

## Organisation suggérée (libre au groupe)

```text
mlops/
  pipelines/      dvc.yaml, étapes prepare / train / evaluate / export / package
  training/       code d'entraînement par cas d'usage (appelle le code des groupes IA)
  monitoring/     calcul PSI / KS, concordance humain-IA
  examples/       exemples de contrats (générés)
```
