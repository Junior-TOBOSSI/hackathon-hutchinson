# Contrat de livraison des modèles (groupes Quality, PPE, Behavior)

Les groupes IA restent maîtres de leur architecture, de leur entraînement, de leur prétraitement et de leurs performances. Ce contrat fixe uniquement **ce qu'on reçoit** pour intégrer un modèle sans aller-retour. Il **réutilise** les contrats existants, sans en créer de nouveaux :

| Besoin | Contrat existant |
|---|---|
| Manifeste du modèle | `visionhub.integration.mlops.ModelPackage` (`argos.model-package/1`) |
| Code d'inférence | `visionhub.analyzer.Analyzer` → `AnalysisResult` |
| Sorties par cas d'usage | `QualityDetails`, `SafetyDetails`, `WorkstationDetails` ; détecteurs `PPEDetector` / `BehaviorDetector` |
| Dataset | `DatasetRef` (version, split, empreinte ; **jamais les données**) |
| Évaluation | `EvaluationMetrics` |
| Versions | MLflow / Unity Catalog → `ModelRef` |

## 1. Structure d'une livraison

```text
<livraison>/
  model-package.json     manifeste ModelPackage (obligatoire)
  README.md              architecture, classes, limites connues, contact
  requirements.txt       dépendances d'inférence épinglées (==)
  train.py               code d'entraînement (lit sa configuration, ne contient aucune donnée)
  evaluate.py            code d'évaluation, qui produit les métriques de EvaluationMetrics
  config.yaml            hyperparamètres et chemins de dataset (placeholders, pas de chemins personnels)
  <module>.py            classe Analyzer (ou détecteur PPE/Behavior) référencée par analyzer_class
  <poids>                fichier de l'artefact (onnx, pt…) : HORS Git si entraîné sur données Hutchinson
```

Les poids entraînés sur des données Hutchinson ne passent **jamais** par Git. Ils sont livrés par MLflow / Unity Catalog (`mlflow.<flavor>.log_model` puis `register_model`) ou par un dépôt de fichiers autorisé. Le manifeste en donne le **sha256**.

## 2. Entrées et sorties

- **Entrée de `analyze(image, meta)`** : image BGR `uint8 (H, W, 3)` (convention OpenCV), déjà recadrée par le ROI global. Le redimensionnement et la normalisation propres au modèle sont **à la charge du livrable** et décrits dans `preprocessing`.
- **Sortie** : `AnalysisResult` avec `score ∈ [0, 1]` (**plus haut = pire**, score brut, sans décision), `model_name` = nom UC/MLflow, `model_version` = version, et `details` du bon type.
- **Erreurs** : **lever une exception**, ne jamais renvoyer un faux « conforme ».
- **Imports lourds** (torch, ultralytics, onnxruntime) : uniquement dans `load()`.
- **Classes** : liste ordonnée dans `classes`. Pour Quality, `["OK", "NOK"]` ; le score est la probabilité de NOK.
- **Post-traitement** : seuils recommandés dans `thresholds` (`low` / `high`). La décision finale reste celle de la couche commune.
- **Option serving Databricks** : modèle pyfunc qui accepte `dataframe_records: [{image_base64}]` et renvoie `predictions: [{class, anomaly_score}]` (le contrat validé en DBX-00). Il est alors consommable tel quel par `mlops.databricks.inference`.

## 3. Dataset et évaluation

- `DatasetRef` : nom, version (DVC ou empreinte du manifeste), `split_strategy` (**`by_sequence` obligatoire pour Quality**), effectifs par split, classes.
- `EvaluationMetrics` sur un split **jamais utilisé pour choisir le modèle** : métriques globales et par classe, matrice de confusion, seuils recommandés, latence CPU p50/p95.
- Pour Quality, au minimum `recall_nok` et `false_reject_rate`.

## 4. Vérification avant livraison

```powershell
& $py -m mlops.delivery.validate_delivery <dossier_livraison>
```

Le validateur vérifie que le manifeste respecte `ModelPackage`, que les fichiers obligatoires sont présents, que les dépendances sont épinglées, que la classe `analyzer_class` est importable (s'il est lancé dans un environnement qui contient les dépendances) et que le sha256 de l'artefact correspond, quand celui-ci est présent localement.

Le **test de contrat** ARGOS (`pytest tests/test_contract.py`) doit passer avec le modèle branché dans `usecases/<cas>/config.yaml`.

## 5. Ce que l'intégration fait ensuite (MLOps)

1. Enregistrement ou vérification de la version dans Unity Catalog, avec ajout du modèle à `ARGOS_DBX_MODELS_FILE`. Il apparaît alors dans `/api/models/overview`.
2. Si le modèle est servi : endpoint CPU en scale to zero, version explicite ; l'adaptateur réutilisé est `EndpointClient`.
3. Approbation humaine (`/api/mlops/models/{id}/versions/{v}/approve`), puis alias, puis déploiement : trois étapes distinctes.
