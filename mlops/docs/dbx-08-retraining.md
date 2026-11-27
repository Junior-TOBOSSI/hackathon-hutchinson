# DBX-08 — Réentraînement automatique

Statut : DBX-08A (backend) livré en local sur `feat/argos-integration`, sans push ni merge.
Aucun entraînement, aucune mutation Databricks, aucun job, aucun warehouse. Le planificateur
est désactivé et le verrou distant fermé.

## 1. Correction prioritaire : un seul chemin de lancement (commit `38a09dc`)

### Audit des routes capables de déclencher un job

| Route | Avant | Après |
|---|---|---|
| `POST /api/models/{id}/retrain` | `DatabricksJobBackend.submit` → `run_now` du job d'entraînement, paramètres par défaut, **sans verrou, ni contrôles, ni idempotence** | Raccordée à `TrainingService.launch` (`source=legacy:/models/retrain`). 403 sans autorisation ; 422 sans `dataset_id`, `version` et `idempotency_key` explicites. Le pipeline est déduit du modèle uniquement s'il est unique. |
| `POST /api/mlops/jobs/{job}/run` | `connector.trigger_job` : les deux jobs d'entraînement et `argos-poc-drift-monitor` étaient lançables **sans verrou** | Les jobs d'entraînement sont toujours refusés (« passer par `/api/mlops/training/launch` »). Les autres jobs exigent `HOVIS_TRAINING_REMOTE=1` puis la liste autorisée. Chaque tentative est journalisée. |
| `POST /api/mlops/training/launch` | Verrou vérifié après la validation | Verrou vérifié **avant** tout autre travail, juste après la relecture idempotente. Journal à chaque issue. |
| `POST /api/mlops/training/runs/{id}/cancel` | Verrou | Verrou et journal. |
| `DatabricksJobBackend.submit` | Second chemin de lancement | Désactivé (lève une erreur). |
| Scripts `mlops/databricks_poc/*` | CLI manuels, hors passerelle | Inchangés (non exposés par l'API). |

Ajouts :
- **Journal append-only** `ARGOS_MLOPS_HOME/training/launch_audit.jsonl`. Il enregistre chaque
  tentative : issue (`submitted`, `replayed`, `refused_lock`, `refused_checks`, `uncertain`,
  `refused_incomplete`…), source, pipeline, dataset et clé.
- `GET /api/mlops/training/launch-audit` et `GET /api/mlops/training/launch-guard`, qui donne
  l'état effectif du processus.

### Vérification sur la passerelle 8020

La passerelle a été redémarrée avec `env -u HOVIS_TRAINING_REMOTE -u HOVIS_RETRAIN_SCHEDULER`.
La variable est absente du shell, de l'environnement utilisateur et de l'environnement machine.

- `launch-guard` renvoie `remote_launch_enabled: false`.
- 7 routes de lancement ou d'annulation testées renvoient **403**, sans aucun appel à `run_now`.
- Le dernier run Databricks reste `741986436941977` (lecture seule) : aucun job n'a été lancé.

## 2. Politiques (`mlops/retraining/`)

- **`RetrainPolicyConfig`** est un DTO MLOps ; les contrats Core ne changent pas. Il porte :
  - le cas d'usage, le modèle, le pipeline et la version du code scientifique (commit du
    pipeline, figé à l'enregistrement) ;
  - la famille de datasets et la stratégie de sélection : `latest_published` ou `pinned` ;
  - l'état actif ou inactif, le mode `manual` ou `auto`, la logique `AND` ou `OR` ;
  - les conditions et les garde-fous.
- **Cohérence vérifiée** à chaque enregistrement :
  - le pipeline enregistre bien dans le modèle ;
  - le cas d'usage est celui du modèle ;
  - la famille est déclarée par le pipeline ;
  - une version épinglée est bien publiée.
- **Versionnement.** SQLite `ARGOS_MLOPS_HOME/retraining.sqlite`, en insertion seule : toute
  modification, activation ou désactivation crée une nouvelle version, et l'historique est
  conservé. Aucun modèle existant n'est modifié.

## 3. Conditions et rigueur statistique

Chaque condition a un état : `satisfied`, `not_satisfied` ou `unavailable`. Une condition
indisponible n'est jamais satisfaite.

**Combinaison des conditions :**
- **aucune condition active** : la politique ne déclenche jamais ;
- **AND** : toutes les conditions actives doivent être satisfaites ;
- **OR** : au moins une satisfaite, et toutes les conditions marquées **requises** satisfaites.

**Les cinq conditions :**
- **Dérive persistante.**
  - Le Monitoring enregistre désormais une ligne `drift_windows` par fenêtre journalière
    distincte. Plusieurs collectes de la même fenêtre restent une seule ligne.
  - Seules comptent les fenêtres dont le statut est `available`, avec une référence
    représentative et compatible, des effectifs suffisants et une origine autorisée (réelle par
    défaut).
  - Il faut N fenêtres distinctes consécutives (N ≥ 2) au niveau requis.
  - Pour un modèle du registre sans inférence reliée par une référence exacte de paquet, la
    condition est **indisponible** (c'est le cas aujourd'hui).
- **Nouvelles annotations.**
  - Le décompte part de la version du dataset utilisée par le **dernier entraînement réussi**
    de ce pipeline sur cette famille.
  - Les manifests sont comparés par identité d'image (sha256) : seuls comptent les ajouts et
    les changements de label, dans les splits train et validation, avec une revue
    `validated`, `corrected` ou `imported`.
  - Ne comptent pas : les validations sans changement, les modifications du split test
    (signalées à part), les images non revues, les doublons. Les corrections brutes du Core
    ne comptent jamais.
- **Dégradation de performances** : indisponible tant qu'il n'existe pas de vérité terrain
  représentative de la production.
- **Planification** : un intervalle en jours depuis le dernier entraînement réussi ; la
  condition est indisponible s'il n'y en a pas.
- **Demande manuelle** : une demande en attente est consommée par une seule proposition.

## 4. Propositions, garde-fous et lancement

- **Proposition.** Une évaluation éligible d'une politique active crée une proposition,
  unique par preuve (`UNIQUE(policy, evidence_key)`) : jamais deux propositions pour la même
  preuve.
- **Garde-fous** (côté serveur) :
  - budget mensuel et délai minimal, y compris depuis le dernier entraînement du pipeline ;
  - plages horaires ;
  - CPU uniquement ;
  - aucun entraînement concurrent du pipeline ;
  - version du code inchangée ;
  - verrou distant ;
  - **une preuve simulée ne déclenche jamais de calcul réel**.
- **Au lancement, tout est re-vérifié :**
  - la politique n'a pas changé de version et reste active ;
  - les conditions sont toujours réunies (y compris les demandes manuelles consommées par
    cette proposition) ;
  - les garde-fous sont toujours respectés.
- **Réservation atomique.** Une transaction SQLite `BEGIN IMMEDIATE` vérifie le budget et le
  délai, inscrit la réservation dans le registre et fait passer la proposition à `launching`.
  Des évaluations ou acceptations concurrentes ne peuvent donc ni dépasser le budget ni lancer
  deux fois. Un test le vérifie avec 5 acceptations simultanées : un seul lancement.
- **Lancement.** Il passe uniquement par `TrainingService.launch`, avec la clé stable
  `policy-<proposal>` et la source `policy:<id>@v<n>`.
  - Réponse douteuse : la proposition passe à `uncertain` et le budget reste compté. La
    réconciliation relance avec la **même** clé (déduplication côté Databricks).
  - Refus de `TrainingService` : la réservation est libérée.
- **Mode manuel** : l'AI Leader consulte, accepte (lancement) ou refuse ; tout est journalisé.
- **Mode automatique** : un lancement n'a lieu que si toutes ces conditions sont réunies :
  - planificateur activé (`HOVIS_RETRAIN_SCHEDULER=1`, désactivé par défaut) ;
  - politique active et en mode `auto` ;
  - conditions satisfaites et garde-fous respectés ;
  - verrou `HOVIS_TRAINING_REMOTE=1`.
  
  Une évaluation explicite ne lance jamais. Ce mode est testé avec un fournisseur de jobs
  simulé.
- **Après l'entraînement**, le modèle reste candidat : aucun alias, aucune approbation, aucun
  déploiement. `GET /comparison` ne présente l'écart avec le champion comme mesure fiable que si
  les empreintes du split de test sont identiques. Il réutilise les performances du Monitoring,
  sans second registre.

## 5. API `/api/mlops/retraining`

- `GET kpis`, `scheduler`, `options`
- `GET` / `POST policies`, `GET` / `PUT policies/{id}`
- `POST policies/{id}/activate|deactivate|manual-request|evaluate`
- `GET evaluations`, `proposals`, `proposals/{id}`
- `POST proposals/{id}/accept|reject|reconcile`
- `GET ledger`, `audit`, `comparison`

## 6. Tests

- `test_launch_guard.py` : 7 tests.
- `test_retraining.py` : 31 tests :
  - versionnement et cohérence des politiques ;
  - combinaisons AND / OR, conditions requises ;
  - dérive : fenêtres distinctes, références, origines ;
  - collectes répétées d'une même fenêtre ;
  - décompte des annotations ;
  - performance indisponible, planification, demande manuelle ;
  - propositions sans doublon ;
  - acceptation unique et refus ;
  - verrou, garde-fous, budget concurrent, changement de politique ;
  - preuve simulée, réconciliation, libération de réservation ;
  - mode automatique, planificateur désactivé ;
  - comparaison, routes.
- Suite complète : 187 tests réussis, 10 ignorés.

## 7. Fichiers partagés modifiés (pour le merge)

| Fichier | Modification |
|---|---|
| `mlops/training/service.py` | `LaunchAudit`, `launch_guard()`, `pipeline_for_model()`, verrou vérifié en premier dans `launch()`, paramètre `source`, journal. |
| `mlops/api/training_routes.py` | `GET /launch-guard`, `GET /launch-audit`. |
| `mlops/api/routes.py` | Ancienne route `retrain` raccordée, route `jobs/{job}/run` journalisée, inclusion des routes `retraining`. |
| `mlops/databricks/connector.py` | Garde de `trigger_job` (jobs d'entraînement refusés, verrou). |
| `mlops/databricks/training.py` | `DatabricksJobBackend.submit` désactivé. |
| `mlops/monitoring/store.py`, `mlops/monitoring/service.py` | Table et enregistrement `drift_windows` à la collecte. |
| Tests `test_databricks_unit.py`, `test_training.py` | Adaptation à la nouvelle garde. |
