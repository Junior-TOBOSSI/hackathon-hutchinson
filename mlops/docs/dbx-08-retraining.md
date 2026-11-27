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

## 8. DBX-08B — Interface « Politiques de réentraînement »

**Training Factory.** Un sélecteur de vue apparaît sous l'en-tête : « Entraînements » ou
« Politiques de réentraînement » (`?section=training&view=policies`). La vue Entraînements
n'est pas modifiée.

**La vue Politiques** (`training/policies/`) comprend :
- **cinq KPI** : politiques (actives, automatiques), propositions en attente ou incertaines,
  lancements du mois, état du planificateur, état du verrou distant ;
- **le catalogue** des politiques, avec un filtre par modèle (`&model=`) quand on arrive
  depuis Monitoring, et la liste des propositions à traiter ;
- **un formulaire de création et de modification** : cas d'usage, modèle, pipeline (avec la
  version du code affichée), famille, sélection de version (dernière publiée ou épinglée), mode
  manuel ou automatique, combinaison ET / OU, état actif ;
  - les cinq conditions, avec leur option « requise » en OU et leurs seuils ;
  - les garde-fous : budget, délai minimal, plage horaire ;
  - un commentaire de version. Une modification crée une nouvelle version ;
- **le détail** d'une politique :
  - actions : activer ou désactiver (nouvelle version), modifier, évaluer maintenant (aucun
    lancement), demande manuelle ;
  - cinq onglets : Configuration, Évaluation (états des conditions et des garde-fous),
    Propositions, Historique des versions, Journal d'audit ;
  - dans Propositions : raisons, « Vérifier pipeline et dataset » (via `/training/validate`, en
    lecture seule), acceptation confirmée qui lance par `TrainingService.launch`, refus motivé,
    réconciliation des réponses incertaines.

**Monitoring.** L'onglet Alertes du détail d'un modèle du registre propose seulement un lien
« Voir les politiques de ce modèle ». Les signaux de réentraînement restent en lecture seule.

**Correction trouvée pendant la recette.** Le garde-fou CPU détectait le texte « gpu » dans la
configuration (`gpu: false`), d'où un faux positif. Il exige désormais une déclaration
explicite : `gpu: false` et un type de calcul CPU. Sans déclaration, la demande est refusée.

### Recette fonctionnelle simulée (passerelle 8020 : verrou fermé, planificateur désactivé)

Politique « Recette DBX-08 — Qualité 702 » : `quality-industrial` / pipeline
`quality-industrial` (code `394a86a937`) / `quality-synthetic-3c`, dernière version publiée,
mode manuel, OU, cinq conditions.

1. **Création** : v1 créée. Une famille non déclarée par le pipeline est refusée (422).
2. **Évaluation : non éligible.**
   - Dérive : indisponible (aucune inférence reliée au modèle par une référence de paquet).
   - Annotations : 0 nouvelle depuis v1.
   - Performance : indisponible (pas de vérité terrain).
   - Planification : prochaine échéance le 27/12.
   - Demande manuelle : aucune.
   - Garde-fous : verrou fermé ; délai minimal non écoulé (dernier entraînement le 27/11).
3. **Demande manuelle** suivie d'une évaluation : éligible, une proposition est créée. Une
   nouvelle évaluation ne crée pas de doublon.
4. **Acceptation : 409** « guardrails: remote_lock ». Le registre reste vide, aucune
   réservation n'est prise, et la liste des runs Databricks est inchangée (dernier :
   741986436941977).
5. **Journal** : création, évaluations, demande, proposition, acceptation, refus.

Recette visuelle : `http://127.0.0.1:5174/ai-leader?section=training&view=policies`.

### Fichiers partagés modifiés en DBX-08B

| Fichier | Modification |
|---|---|
| `argos-ui/src/pages/ai-leader/training/TrainingFactory.tsx` | Sélecteur de vue ; la vue Entraînements est encapsulée sans changement. |
| `argos-ui/src/pages/ai-leader/monitoring/ModelDetail.tsx` | Bouton « Voir les politiques de ce modèle ». |
| `mlops/retraining/service.py`, `mlops/tests/test_retraining.py` | Garde-fou CPU explicite. |

Nouveaux fichiers : `argos-ui/src/api/retraining.ts` et
`argos-ui/src/pages/ai-leader/training/policies/` (`PoliciesView.tsx`, `PolicyForm.tsx`,
`shared.tsx`, `policies.css`).

## 9. Limites restantes

- **Dérive** : la condition reste indisponible pour les modèles du registre. Il faut d'abord la
  traçabilité exacte des paquets côté Edge (modèle UC, version, SHA-256) : c'est une demande
  de coordination de DBX-07B.
- **Performance de production** : indisponible sans échantillon étiqueté représentatif.
- **Identité des acteurs** : la passerelle locale n'a pas d'authentification ; les actions sont
  journalisées sous le rôle `ai_leader`. Le planificateur apparaît sous `scheduler`.
- **Planificateur** : simple processus local (thread) dans la passerelle. Il s'arrête avec
  elle ; au redémarrage, le budget et l'idempotence restent garantis par SQLite.
- **Budget** : compté par politique. Un budget global par modèle reste à décider.
- **Concurrence** : vérifiée au moment du lancement (lecture des runs) ; un run démarré par un
  autre canal entre ce contrôle et la réservation n'est pas exclu.
- **Persistance** : uniquement en SQLite local, sans synchronisation multi-postes. Le contrat
  Core `RetrainingPolicy` n'est pas modifié.
- **Ancien mode `PUT /models/retrain-mode`** : il reste en mémoire et n'est relié à aucun
  lancement. Le remplacer par les politiques reste à décider.
