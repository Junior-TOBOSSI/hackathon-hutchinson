# DBX-05 — Training Factory et intégration Quality

Commits : `7220b2b` (05B, orchestration), `29c92e3` (05C, interface), `830ba3e` (correctifs). Base : `b3bbc5b`, obtenue par fast-forward depuis `243b232`.

## 1. Pipelines déclaratifs

Chaque pipeline est décrit dans `mlops/pipelines/<id>/pipeline.yaml` :
- cas d'usage, classes, exigences sur le dataset (format, extensions, splits obligatoires, champ de groupe) ;
- paramètres : de base, avancés ou imposés, avec type et bornes ;
- calcul, job, points d'entrée, sorties, destination MLflow, protocole d'évaluation.

Ajouter un pipeline (EPI, Comportement, Poste) revient à ajouter un dossier ; Training Factory ne change pas.

| Pipeline | État | Raison |
|---|---|---|
| `quality-demo` | **Exécutable** | Job existant `argos-poc-quality-training`, serverless CPU. Aucun hyperparamètre exposé : les deux configurations sont fixées dans le code. La version du dataset se choisit **pour chaque exécution**, via les paramètres du notebook, sans modifier la définition du job. |
| `quality-industrial` | **Non exécutable** | Le job `hovis-quality-industrial-training` n'est pas créé (création soumise à autorisation). Le code est présent. |

## 2. Kit Quality

Le kit est intégré **sans modification** dans `mlops/pipelines/quality_industrial/kit/`, depuis `394a86a`. `PROVENANCE.md` donne le SHA Git de chaque fichier, et un test vérifie l'égalité octet pour octet. Le kit est exclu de `ruff`.

**Paramètres** : ceux réellement lus par `train.py`, avec les valeurs du groupe inchangées.
- De base : `epochs` 30, `patience` 10, `batch` 32, `seed` 0.
- Avancés : `imgsz` 128, `erasing` 0, `flipud` 0.5, `hsv_v` 0.6, `scale` 0.6, `rappel_vise` 0.90.
- Imposés : `modele_base` = `yolo26n-cls.pt`, et **`fusionner_test` = false**.
- Il n'y a pas de taux d'apprentissage.

**Wrapper** `run_pipeline.py`, exécuté dans le job :
1. Matérialisation de la version du dataset : chaque SHA-256 est vérifié, `validation` devient `val`, `repartition.csv` est régénéré avec les rafales, et aucune rafale ne peut se trouver dans deux splits.
2. Écriture du YAML effectif.
3. Appel de `train.py`, **sans** `--ecraser` **ni** `--fusionner-test`.
4. Appel de `evaluer.py` sur le **test**.
5. Appel de `export_onnx.py`, si `onnx` et `onnxruntime` sont installés.
6. **Un seul** run MLflow (le suivi MLflow propre à Ultralytics est désactivé), contenant :
   - les tags : pipeline, commit, dataset, empreinte du manifeste, empreintes des splits, job et exécution Databricks ;
   - les paramètres ;
   - les métriques par époque et les métriques de test ;
   - les artefacts, **sans aucune image**.
7. Enregistrement d'un **candidat** :
   - idempotent : pas de doublon pour un même run ;
   - sans alias, sans approbation, sans changement de la version servie.
   - Relancer la même requête après un entraînement réussi ne réentraîne pas : seul l'enregistrement est repris.

**Test local de bout en bout, réalisé** : il a utilisé les **vrais** scripts du groupe, sur `quality-synthetic-3c`, avec Ultralytics 8.4.219, PyTorch en CPU et un MLflow SQLite local.
- L'entraînement (2 époques) puis l'évaluation sur le test ont produit un seul run MLflow, avec les métriques par époque et les métriques de test.
- Les artefacts `evaluation/metriques.json`, `predictions.csv` et `rapport_evaluation.md` sont présents.
- Le candidat v1 est enregistré, **sans alias**.
- La seconde exécution de la même requête a renvoyé `resumed` : ni réentraînement, ni nouvelle version.
- L'export ONNX a été sauté, car `onnx` n'est pas installé localement.

## 3. Datasets

- Le `DatasetResolver` passe par le catalogue indépendant (`scope_id`, `manifest`), sans raccourci par le modèle.
- Le champ facultatif `group` à l'import est conservé dans les manifestes publiés (source pour 5S, rafale pour Quality). L'ajout est rétrocompatible.
- `quality-synthetic-3c` est généré localement : 108 JPG de 126×86 px, 18 rafales, découpage par rafale (72 / 18 / 18). L'import est préparé mais pas effectué.
- Un dataset sans split de validation (presse-5s) est **refusé** par les pipelines qui exigent ce split.

## 4. Routes (`/api/mlops/training`)

| Route | Rôle |
|---|---|
| `pipelines` | Pipelines déclarés et leur état d'exécutabilité |
| `pipelines/{id}/datasets` | Datasets compatibles avec un pipeline |
| `datasets/{d}/versions/{v}/preview` | Aperçu d'une version de dataset |
| `validate` | Contrôles de compatibilité |
| `launch` | Lancement d'un entraînement |
| `summary` | Indicateurs |
| `runs` | Catalogue des entraînements |
| `runs/{id}` | Détail d'un entraînement |
| `runs/{id}/cancel` | Annulation |
| `runs/{id}/logs` | Logs Databricks |
| `mlflow-runs/{r}/history` | Historique des métriques |
| `mlflow-runs/{r}/evaluation` | Évaluation |
| `mlflow-runs/{r}/predictions` | Prédictions |
| `mlflow-runs/{r}/artifacts` | Liste des artefacts |
| `mlflow-runs/{r}/artifact` | Lecture d'un artefact |

**`launch` et `cancel`** renvoient **403** tant que `HOVIS_TRAINING_REMOTE` ne vaut pas `1`. Ils utilisent le jeton d'idempotence de Databricks : un double clic ou une réponse incertaine ne crée jamais un second job.

## 5. Mesures sur les données réelles (via 5174)

- **Catalogue** :
  - 1,1 s à froid, puis servi depuis le cache ;
  - `TR-413658636976172` est relié exactement à ses 2 runs MLflow et aux versions v1 et v2, par le tag `databricks.job_run_id` ;
  - les 3 exécutions en échec de DBX-00 n'ont aucun run, ce qui est exact.
- **Évaluation d'un run `quality-demo`** : 14 s au premier accès (listing MLflow), puis immédiate ; la matrice vient de `reports/confusion_matrix_test.json`.
- **Liste complète des artefacts** : 24 s au premier accès, puis mise en cache 1 h.

## 6. Limites

- Le lancement distant est désactivé, et aucun job, expérience ou modèle Unity Catalog n'a été créé.
- Les prédictions par image n'existent que pour `quality-industrial` (`predictions.csv`). `quality-demo` n'en produit pas.
- `predictions.csv` ne contient pas les probabilités par classe : elles ne sont pas affichées.
- Une image n'est reliée à son entrée du manifeste que si le couple (classe, nom) est unique dans le test.
- Le lien « Ouvrir dans MLflow » dépend des tags du run.
- `tri_nok.csv` manque : aucun dataset `quality-industrial` ne peut être construit.

## 7. Plan des premiers lancements Databricks (à autoriser)

Tout se fait en serverless CPU, sans GPU, sans warehouse et sans endpoint.

1. **`quality-demo` sur `synthetic-v2`**
   - Actions : passer `HOVIS_TRAINING_REMOTE=1`, puis lancer depuis l'assistant. Un seul job, existant ; environ 5 minutes de calcul.
   - Vérifier : dataset = `synthetic-v2` dans les runs MLflow, versions candidates en v3 et v4, alias et version servie inchangés.
   - **Point d'attention** : le code téléversé dans le Volume est encore celui de DBX-00, qui sélectionne lui-même le champion et le challenger. Avant ce lancement, il faut **décider** :
     - soit mettre à jour le code distant (évolution Delta « option B », et suppression de l'attribution automatique des alias) ;
     - soit accepter son comportement d'origine.

     Je recommande la mise à jour, que je ferai avec `upload_code`, sans lancer de job.
2. **Mise en place de `quality-industrial`**, sans entraînement :
   - téléverser `mlops/` (wrapper et kit) dans `runs/hovis/code` ;
   - créer le job `hovis-quality-industrial-training` : serverless CPU, environnement `ultralytics==8.4.219`, `torch` CPU, `onnx`, `onnxruntime`, `mlflow==3.18.0`, paramètre de job `request` ;
   - créer l'expérience `/Shared/HOVIS/quality-industrial` et le modèle Unity Catalog `workspace.argos_poc.quality_industrial` ;
   - déposer `yolo26n-cls.pt` avec son SHA-256.
3. **Import de `quality-synthetic-3c`** : `python -m mlops.datasets_prep.quality_synthetic_3c import --i-have-explicit-authorization` (108 images, environ 1 Mo).
4. **Premier entraînement `quality-industrial` sur `quality-synthetic-3c`** :
   - un seul job, avec les paramètres par défaut du groupe (30 époques maximum) ;
   - durée attendue de quelques minutes sur CPU (non mesurée sur Databricks) ;
   - vérifier : courbes, matrice avec `A_VERIFIER`, galerie, artefacts, candidat sans alias.
5. **Plus tard** : `quality-industrial` sur les données réelles, seulement après réception de `tri_nok.csv` et ton autorisation de transfert.

## 8. DBX-05D — recettes Databricks (27/11/2026)

État protégé relevé avant, pendant et après (`snapshot_*.json`) : **inchangé**. Quality Demo v2 reste champion, approuvée et servie par `argos-quality-poc` (READY) ; v1 reste challenger, non approuvée. Warehouse arrêté, aucun cluster.

| Opération | Résultat |
|---|---|
| Code distant de `quality-demo` | Ancien `b1a74627…` sauvegardé (`code/_backup/` et `ARGOS_MLOPS_LOCAL/backups/`) ; version finale `15eb0663…` vérifiée (SHA-256). Plus d'alias automatique, versions candidates, écritures Delta par version, `--request-id`. |
| 1er essai de lancement de `quality-demo` | **Refusé par Databricks** (`{{job.run_id}}` non accepté dans les paramètres passés au lancement) ; **aucune exécution créée**. Corrigé : lien exact par identifiant de requête. |
| Exécution de `quality-demo` sur `synthetic-v2` | Job run `969619535979825`, **SUCCESS en 111 s**. Runs MLflow `7a5d09be…` et `6e1fde32…`, versions **v3 et v4 candidates** (sans approbation ni alias), manifeste `019e804d…`. Exactitude de test 0,85 et 0,825, identique à v1 : contenu d'entraînement inchangé. |
| Import de `quality-synthetic-3c` v1 | Publiée via le catalogue : 108 JPG (72 / 18 / 18), 18 rafales préservées dans le manifeste (`group`), aucune rafale à cheval sur deux splits ; manifeste `a4d9e9dd…`. |
| Installation de `quality-industrial` | 24 fichiers de code vérifiés dans `runs/hovis/code` ; poids `yolo26n-cls.pt` (`0dd6f8db…`, release officielle Ultralytics v8.4.0) ; expérience `/Shared/HOVIS/quality-industrial` (858114336591834) ; modèle `workspace.argos_poc.quality_industrial` ; job `315903472839295` (serverless CPU, sans nouvelle tentative ni planification). |
| Exécution de `quality-industrial` | Job run `540537827556689`, **ÉCHEC à l'installation des bibliothèques** (environ 227 s de calcul, 567 s au total) : `protobuf` 5.29.4 → 7.36.2, `numpy` 1.26.4 → 2.2.6, `pyarrow` 15.0.2 → 26.0.1, puis le noyau Python ne démarre pas. **Aucun entraînement, aucun run MLflow, aucune version.** Log : `ARGOS_MLOPS_LOCAL/training/logs/540537827556689.txt`. Pas de relance. |

Correctif proposé, non appliqué : environnement épinglé sur les versions du cœur (voir `pipeline.yaml`). Il demande une nouvelle autorisation : mise à jour de l'environnement du job, puis une seule exécution. Le verrou `HOVIS_TRAINING_REMOTE` est refermé.

## 9. DBX-05D-FIX — environnement Quality corrigé (27/11/2026)

**Cause de l'échec 540537827556689** : dépendances non épinglées (`onnx`, `onnxruntime`, `mlflow`… et leurs dépendances transitives) qui ont remplacé des paquets du cœur de l'environnement serverless 3 (Python 3.12.3, Ubuntu 24.04) : protobuf, numpy, pyarrow.

**Résolution** : `uv pip compile`, cible Linux aarch64 / CPython 3.12, avec contraintes sur les paquets préinstallés.
- `pandas` 1.5.3 n'a pas de wheel pour Python 3.12 et n'est requis que par `mlflow` (`<4`) : non épinglé, il est conservé.
- `opencv` 4.11.0.86 est la dernière série compatible avec numpy 1.x.
- `torch` aarch64 sur PyPI est CPU uniquement ; le seul paquet « nvidia » est `nvidia-ml-py`, une simple interface Python.

**Dépendances finales** : numpy==1.26.4, protobuf==5.29.4, pyarrow==15.0.2, grpcio==1.71.0, grpcio-status==1.71.0, scipy==1.13.1, pillow==10.3.0, matplotlib==3.8.4, torch==2.5.1, torchvision==0.20.1, ultralytics==8.4.219, opencv-python==4.11.0.86, onnx==1.17.0, onnxruntime==1.20.1, onnxslim==0.1.98, mlflow==3.18.0, pyyaml.

**Job `315903472839295`** : configuration précédente sauvegardée (`runs/hovis/backups/` et `ARGOS_MLOPS_LOCAL/backups/`). Seul l'environnement a été modifié. Le job reste serverless, sans planification ni nouvelle tentative, et le kit du groupe est identique (16 fichiers vérifiés).

**Exécution `741986436941977`** : **SUCCESS**, 201 s au total.
- Durées des phases : contrôle d'environnement 3,8 s, matérialisation 9,9 s, entraînement 43,9 s, évaluation 6,1 s, export 6,1 s.
- Contrôle d'environnement réussi : aarch64, 4 CPU, sans CUDA, versions du cœur conservées (y compris pandas 1.5.3 et databricks-sdk 0.49.0).
- Run MLflow `f6fd2e72798f490a8296145efad77f2a`.
- Entraînement : 17 époques sur 30 (arrêt anticipé), meilleure époque 8, seuil NOK 0,454 (choisi sur la validation).
- Test (18 images, **synthétiques**) : rappel NOK 100 %, 0 faux rejet, 0 défaut manqué, latence 12,9 ms en moyenne et 22,7 ms au P95. Ce n'est pas une mesure industrielle.
- **ONNX** : exporté, `onnx.checker` et ONNX Runtime réussis. Le rapport du groupe donne un écart maximal de probabilité de 1,48e-2 entre le `.pt` et l'`.onnx`, avec 0 verdict différent, et recommande de livrer le `.pt` tant que cet écart n'est pas compris. **Non validé pour l'Edge.**
- **Candidat** : `workspace.argos_poc.quality_industrial` v1, sans alias ni approbation. Le modèle est exposé par `/api/mlops/models` et `/status`.
