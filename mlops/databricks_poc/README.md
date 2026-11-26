# DBX-00 — Databricks Feasibility Proof of Concept

Une boucle complète, réelle mais minimale, sur le workspace d'essai Databricks, avec des **données synthétiques uniquement** (carrés OK / carrés interrompus ou déformés NOK, sans rapport avec un produit réel) :

```text
dataset synthétique (PC) → Volume Unity Catalog → Lakeflow Job serverless CPU → MLflow Tracking
→ Models in Unity Catalog (v1, v2, alias) → Model Serving (endpoint CPU Small, scale to zero)
→ appels HTTPS depuis le PC → simulateur de machine → télémétrie Delta → dérive (PSI) → lecture SQL
```

Résultats détaillés : `%USERPROFILE%\ARGOS_MLOPS_LOCAL\dbx_poc\results\*.json` (hors dépôt).

## Ressources Databricks du POC

| Ressource | Nom / identifiant |
|---|---|
| Schéma | `workspace.argos_poc` |
| Volume | `workspace.argos_poc.images` (`synthetic-v1/`, `code/`, `runs/`) |
| Tables Delta | `annotations` (200), `dataset_versions` (1), `telemetry` (86), `drift_report` |
| Expérience MLflow | `/Shared/ARGOS-POC/quality-demo` (id `996323646496387`) |
| Job d'entraînement | `argos-poc-quality-training` (job `708543846308004`, run réussi `413658636976172`) |
| Job de dérive | `argos-poc-drift-monitor` (job `748026130982075`, run `289718280350722`) |
| Modèle UC | `workspace.argos_poc.quality_demo` : v1 (`challenger`), v2 (`champion`) |
| Endpoint | `argos-quality-poc` : CPU, Small, scale to zero, sert la **v2** |
| Notebook lanceur | `/Shared/ARGOS-POC/run_volume_script` |

Aucun job planifié. Le SQL Warehouse préexistant a été démarré puis **arrêté**.

## Reproduire (PowerShell, racine du dépôt)

```powershell
$py = "$env:USERPROFILE\ARGOS_MLOPS_LOCAL\.venv\Scripts\python.exe"
& $py -m mlops.databricks_poc.audit                          # 00A audit (lecture seule)
& $py -m mlops.databricks_poc.dataset                        # 00B dataset local (seed 2026)
& $py -m mlops.databricks_poc.upload_dataset                 # 00B schéma, Volume, upload, SHA-256
& $py -m mlops.databricks_poc.run_training_job               # 00C/D job serverless + MLflow + UC
& $py -m mlops.databricks_poc.serve --version 1              # 00E création endpoint, attente READY
& $py -m mlops.databricks_poc.inference remote --count 6     # 00E 6 inférences distantes
& $py -m mlops.databricks_poc.inference local --version 1 --compare-with <remote_inference_v1_*.json>  # 00F
& $py -m mlops.databricks_poc.serve --alias champion         # 00E mise à jour vers v2 (même endpoint)
& $py -m mlops.databricks_poc.simulator --cycles 3           # 00G (+ --drift)
& $py -m mlops.databricks_poc.monitoring local-telemetry --version 2
& $py -m mlops.databricks_poc.monitoring push                # 00H Delta via SQL warehouse
& $py -m mlops.databricks_poc.monitoring dqm-check
& $py -m mlops.databricks_poc.monitoring drift-job
& $py -m mlops.databricks_poc.monitoring report
& $py -m mlops.databricks_poc.monitoring stop-warehouse
& $py -m uvicorn mlops.databricks_poc.api:app --host 127.0.0.1 --port 8030   # 00I
```

Le profil CLI `ARGOS` (OAuth) est utilisé pour tout. Les variables `DATABRICKS_CONFIG_PROFILE`, `MLFLOW_TRACKING_URI=databricks` et `MLFLOW_REGISTRY_URI=databricks-uc` sont définies **dans le processus uniquement** (`common.setup_environment`). Aucun jeton n'est lu, affiché ni stocké. Le budget d'inférences distantes (20 au maximum) est imposé par `common.consume_inference_budget`.

## Arrêt et suppression (ressources du POC uniquement)

```powershell
& $py -m mlops.databricks_poc.cleanup                    # simulation : liste ce qui serait supprimé
& $py -m mlops.databricks_poc.cleanup --endpoint-only    # supprime seulement l'endpoint (seule ressource facturable au repos)
& $py -m mlops.databricks_poc.cleanup --yes              # endpoint, jobs, versions et modèle, expérience, schéma (cascade), dossier /Shared/ARGOS-POC
```

Équivalent en CLI pour l'endpoint : `databricks serving-endpoints delete argos-quality-poc --profile ARGOS`.

## Restrictions rencontrées sur le compte d'essai

| Constat | Preuve | Contournement |
|---|---|---|
| Le calcul serverless ne peut pas lire les **Workspace files** (`/Workspace/...`) | `OSError Errno 5` et `403 … Server Side Encryption with Customer provided keys` (run `271044214110977`, notebook de diagnostic `510506731968200`) | code déposé dans le **Volume UC** |
| `spark_python_task` refuse un fichier situé dans un Volume | « Cannot read the python file /Volumes/… » (run `133652317530677`) | **notebook lanceur** qui exécute le script du Volume |
| Les échecs `INTERNAL_ERROR` sont **relancés une fois** par la plateforme malgré `max_retries=0` | `attempt_number` 0 et 1 sur chaque run échoué | coût d'un échec doublé : corriger avant de relancer |
| Unity Catalog interdit `.` dans les clés de tags de version | `Tag key contains reserved characters` | clés `argos_*` avec `_` |
| `search_model_versions` (UC) ne renvoie pas les tags | `TypeError` dans `/poc/models` | lecture par `get_model_version` |
| `data_quality.list_monitor` n'est pas disponible | `NotFound: Could not handle RPC …` | l'API `quality_monitors` fonctionne (moniteur créé, ACTIVE, puis supprimé) |
| Facturation : `system.billing.usage` est lisible mais **vide** pour la journée | requête sans ligne | usage remonté avec plusieurs heures de retard : à revérifier |

## Adaptateur nécessaire pour le Production Engine (non construit)

Une sous-classe `Analyzer` (`use_case = QUALITY`) dans `usecases/quality/`, dont `analyze()` encode l'image en PNG base64, appelle l'endpoint (`RemoteModel.predict`) et renvoie `AnalysisResult(score=anomaly_score, model_name=workspace.argos_poc.quality_demo, model_version=<version servie>, details=QualityDetails())`. Elle **lève une exception** en cas d'erreur HTTP ou de timeout, pour que le `ProductionEngine` enregistre une pièce `ERROR`. Elle se branche via `usecases/quality/config.yaml`, ce qui relève d'une décision du binôme Quality. Le même code peut charger le modèle **localement** (`mlflow.pyfunc.load_model("models:/…/N")`) pour l'Edge hors ligne : les résultats sont identiques (écart ≤ 1e-16).
