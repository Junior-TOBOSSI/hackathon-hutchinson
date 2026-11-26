# DBX-01 — Intégration applicative Databricks

DBX-01 transforme le POC DBX-00 en **services réutilisables** :

- `mlops/databricks/` : configuration, connecteur, adaptateur d'inférence, backends d'entraînement ;
- `mlops/api/` : un routeur FastAPI.

Le POC `mlops/databricks_poc/` reste tel quel, comme référence expérimentale, et les ressources Databricks qu'il a créées sont réutilisées sans être recréées.

## 1. Ce qui a été repris du POC, et ce qui reste expérimental

| Élément du POC | Devenu | Statut |
|---|---|---|
| `common.workspace_client`, PATH de la CLI | `settings.DatabricksSettings.apply_process_environment` | réutilisable |
| Noms des ressources codés en dur | `ManagedModel` + variables `ARGOS_DBX_*` | réutilisable, configurable |
| `inference.RemoteModel` | `inference.EndpointClient` (erreurs typées, version servie, validation du score) | réutilisable |
| `monitoring.sql` | `DatabricksConnector._sql` (sans jamais démarrer de warehouse par défaut, avec cache) | réutilisable |
| `run_training_job` (création et `run_now`) | `connector.trigger_job` (jobs **existants**, liste autorisée, un seul run actif) | réutilisable |
| `dataset.py`, `upload_dataset.py`, `remote/*`, `serve.py`, `cleanup.py`, `simulator.py`, `api.py` (port 8030), budget de 20 inférences | — | **expérimental** (POC uniquement) |

## 2. Démarrer

```powershell
$py = "$env:USERPROFILE\ARGOS_MLOPS_LOCAL\.venv\Scripts\python.exe"   # venv MLOps (SDK Databricks, MLflow 3.18)
& $py -m uvicorn mlops.api.app:app --host 127.0.0.1 --port 8040
# http://127.0.0.1:8040/docs
```

L'authentification passe par le profil CLI `ARGOS` (OAuth) du **processus serveur**. Aucun jeton ne circule dans les réponses ni vers le navigateur. Toutes les variables sont décrites dans `mlops/databricks/settings.py` (modèles gérés, expériences, table de monitoring, warehouse, cache, timeout).

**Intégration au Core** (une ligne dans le Core, à faire par son responsable) :

```python
from mlops.api.routes import create_mlops_router
app.include_router(create_mlops_router(), prefix="/api")
```

## 3. Endpoints (préfixe `/api`)

| Méthode et route | Rôle | Réponse |
|---|---|---|
| GET `/models/overview` | écran AI Leader d'`argos-ui` | `AiOverview` + `servedVersion`, `championVersion`, `approvedVersions`, `dataStatus` |
| POST `/models/{id}/retrain` | relance le job d'entraînement **existant** du modèle | 202 `JobRunInfo` |
| PUT `/models/retrain-mode` `{mode}` | mode MANUEL ou AUTO (`RetrainingPolicy`, en mémoire) | 204 |
| POST `/models/{id}/promote` `{version}` | déplace l'alias `champion` (**ne change pas la version servie**) | `ModelStatus` |
| GET `/mlops/health` | test de connexion | `ConnectionStatus` |
| GET `/mlops/catalogs`, `/mlops/catalogs/{c}/schemas` | Unity Catalog | noms, `SchemaInfo[]` |
| GET `/mlops/experiments`, `/mlops/experiments/{id}/runs` | MLflow | `ExperimentInfo[]`, `RunSummary[]` (MLOPS-01) |
| GET `/mlops/runs/{id}`, `/mlops/runs/{id}/metrics/{key}/history` | runs | `RunSummary`, `MetricPoint[]` |
| GET `/mlops/runs/compare?ids=a,b` | comparaison des métriques et paramètres | tableau métrique × run |
| GET `/mlops/models` | modèles gérés (configuration) | `ManagedModel[]` |
| GET `/mlops/models/{id}/versions` | versions UC | `ModelVersionInfo[]` |
| GET `/mlops/models/{id}/status` | **approbation, alias et version servie** côte à côte | `ModelStatus` |
| GET `/mlops/models/{id}/aliases/{alias}` | résolution d'un alias | `ModelRef` (contrat ARGOS) |
| POST `/mlops/models/{id}/aliases/{alias}` `{version}` | `champion` ou `challenger` uniquement | `ModelStatus` |
| POST `/mlops/models/{id}/versions/{v}/approve` | approbation humaine (tag `argos_approval`) | `VersionStatus` |
| GET `/mlops/models/{id}/monitoring?refresh=` | dernier rapport de dérive | `MonitoringReport` → `MonitoringMetrics` + `DriftMeasure` |
| GET `/mlops/jobs`, `/mlops/jobs/{job_id}/runs`, `/mlops/job-runs/{run_id}` | Lakeflow Jobs | `JobInfo[]`, `JobRunInfo` |
| POST `/mlops/jobs/{name}/run` | déclenche un job **autorisé** (409 si un run est déjà actif) | 202 `JobRunInfo` |
| GET `/mlops/endpoints`, `/mlops/endpoints/{name}` | Model Serving (hors endpoints de fondation) | `EndpointInfo` |

Codes d'erreur : 404 (inconnu), 403 (opération ou alias non autorisés), 409 (run déjà actif, ou warehouse arrêté pour le monitoring), 503 (Databricks injoignable), 502 (autre erreur Databricks).

**Trois notions distinctes, jamais confondues :**

| Notion | Où elle vit | Qui la change |
|---|---|---|
| Approuvée | tag de version UC `argos_approval=approved` | `POST …/approve` (décision humaine) |
| Alias `champion` / `challenger` | alias UC | `POST /models/{id}/promote`, `POST …/aliases/{alias}` |
| Version servie | configuration de l'endpoint | uniquement un déploiement (hors API à ce stade ; `serve.py` du POC) |

## 4. Remplacer les mocks d'`argos-ui` (branche `interface`, lecture seule)

Dans `argos-ui`, l'espace AI Leader appelle `api.aiOverview()`, `retrain()`, `setRetrainMode()` et `promote()` (`src/api/client.ts`), sur les routes `/api/models/...` que **notre API sert déjà telles quelles**. Pour les données réelles, côté frontend :

1. `VITE_USE_MOCK=false` ;
2. le proxy Vite `/api` doit pointer vers `http://127.0.0.1:8040` (aujourd'hui `localhost:8000`, qui deviendra le Core quand le routeur y sera inclus).

Aucune autre modification n'est nécessaire pour afficher les données.

| Champ `AiOverview` (types.ts) | Source réelle | Transformation |
|---|---|---|
| `models[].id/name/useCase/scope` | `ManagedModel` (configuration) | aucune |
| `models[].version` | version **servie** (sinon `champion`) | `v` + numéro |
| `models[].healthPct` | accuracy étiquetée de la dernière fenêtre de monitoring (sinon accuracy de validation du run servi) | × 100, arrondi |
| `models[].recallKoPct` | `test_recall_nok` (sinon `val_recall_nok`) du run de la version servie | × 100 |
| `counts` | calculé sur `healthPct` (≥ 90, 85–90, < 85) | — |
| `drifts[]` | `drift_report` (DriftMeasure en alerte) | texte du PSI par variable |
| `training` | dernière version UC, son run, la version précédente | `step` 5 si servie, sinon 4 |
| `retrainMode` | `RetrainingPolicy` en mémoire | MANUEL ou AUTO |
| `series` (14 jours) | **non disponible** | `[]` : il faut un job de monitoring quotidien |
| `training.absentStoppedPct` / `doubleStoppedPct` | **non disponible** (spécifique au produit) | `null` : à fournir par l'évaluation du groupe Quality |

Point de vigilance côté écran : l'action « Promouvoir en production » d'`argos-ui` déplace l'alias `champion`, mais ne change **pas** la version servie. L'écran devrait afficher `servedVersion` à côté de `championVersion`, déjà présents dans la réponse. C'est une proposition pour le groupe Frontend ; je n'ai pas modifié leurs écrans.

## 5. Activer l'adaptateur d'inférence (plus tard, avec le groupe Quality)

`mlops.databricks.inference.DatabricksQualityAnalyzer` est un `Analyzer` ARGOS (`use_case = quality`) qui renvoie l'`AnalysisResult` partagé. Le nom et la version du modèle sont **lus sur l'endpoint**, et toute erreur (HTTP, timeout, réponse invalide, score hors de [0, 1]) **lève une exception**. Le pipeline et le Production Engine enregistrent alors la pièce en `ERROR`, jamais en `OK`.

Modifications nécessaires, toutes **hors de mon périmètre**, donc à coordonner :

1. `usecases/quality/config.yaml` (groupe Quality) :
   ```yaml
   analyzer_class: mlops.databricks.inference:DatabricksQualityAnalyzer
   params: {endpoint: argos-quality-poc, timeout_s: 30}
   ```
2. Environnement de l'Edge : `databricks-sdk` et un profil d'authentification **de service** (pas un compte personnel), et `mlops/` importable (il ne fait pas partie du package `visionhub` : `pyproject.toml` partagé).
3. Test de contrat : `CONTRACT_MAX_SECONDS` doit couvrir la latence réseau (1 à 3 s mesurées, plus le démarrage à froid si le scale to zero est actif).
4. Le Production Engine n'a **rien** à changer : une exception de l'analyseur y donne déjà `ERROR`.

Hors ligne, le même modèle peut être chargé localement (`mlflow.pyfunc.load_model("models:/<uc_name>/<version>")`). Le DBX-00 a montré des résultats identiques au serving.

## 6. Architecture hybride (entraînement et tracking séparés)

- **Moteur principal** : `training.DatabricksJobBackend`, qui exécute le job Lakeflow existant déclaré dans `ManagedModel.training_job`.
- **Autre moteur** (PC, cluster GPU externe) : `training.use_databricks_tracking(experiment)`, puis journalisation MLflow et `mlflow.register_model(..., "<catalog>.<schema>.<model>")`. Ses runs et versions apparaissent dans la même API.
- `TrainingBackend` est l'interface commune (`submit`, `status`). Il n'y a volontairement ni ordonnanceur ni bascule automatique.

## 7. Limites

- `retrain-mode` est en mémoire : sa persistance relève du Core.
- Le monitoring ne lit la table que si le warehouse tourne (`ARGOS_DBX_WAREHOUSE_AUTOSTART=false` par défaut, pour éviter les coûts), avec un cache de 300 s.
- Un seul modèle est géré aujourd'hui (POC synthétique). Les modèles des groupes s'ajoutent par `ARGOS_DBX_MODELS_FILE`.
- Le déploiement (changer la version servie) n'est pas exposé dans l'API : c'est volontaire tant que le circuit d'approbation n'est pas validé.
- Pas d'authentification sur l'API autonome (localhost uniquement) : ce sera celle du Core.
