# ARGOS — Répartition des chantiers

Cinq groupes travaillent en parallèle sur le monorepo ; l'équipe **Intégration** garde le socle Edge/Core. Contrats : [integration-contracts.md](integration-contracts.md). Règles générales : [AGENTS.md](../AGENTS.md).

## Règles communes

- Référence de départ : le commit **ARGOS-BASELINE** une fois fusionné dans `main` (étiquette proposée `argos-baseline`). Chaque branche part de là.
- Jamais de push direct sur `main`, jamais de force-push, jamais de suppression ou de recréation d'une branche existante. Intégration par **pull request** vers `main`, CI verte, relue par un membre d'un autre groupe.
- Se mettre à jour par `git merge origin/main` (pas de rebase d'une branche partagée).
- **Fichiers protégés** (accord collectif) : `visionhub/contracts.py`, `visionhub/decision.py`, `visionhub/registry.py`, `visionhub/api.py`.
- **Fichiers de l'Intégration** (modification par PR relue par l'Intégration) : `visionhub/**` hors protégés, `tests/*.py`, `tests/production/`, `tests/baseline/`, `frontend/openapi/`, `frontend/src/api/generated/`, `frontend/src/mocks/fixtures/`, `docs/integration-contracts.md`, `.github/workflows/`, `pyproject.toml`, `docker-compose.yml`, `Dockerfile`.
- Jamais de données, d'images, de vidéos, de poids entraînés sur données Hutchinson ni de secrets dans Git (dépôt **public**). Données confidentielles hors du dépôt.
- Avant toute PR : `ruff check .`, `ruff format --check .`, `pytest` ; côté frontend `npm run typecheck && npm test && npm run build`.

## Vue d'ensemble

| Groupe | Branche | Dossiers dont il est responsable |
|---|---|---|
| ARGOS MLOps | `feat/argos-mlops` | `mlops/` |
| ARGOS Frontend | `feat/argos-frontend` | `frontend/` (hors fichiers générés) |
| ARGOS AI PPE | `feat/ai-ppe` | `usecases/safety/ppe/` (à créer) |
| ARGOS AI Behavior | `feat/ai-behavior` | `usecases/safety/behavior/` (à créer), `usecases/workstation/` (5S, **à confirmer**) |
| ARGOS AI Quality | `quality` (existante) | `usecases/quality/` |
| Intégration (Edge/Core) | `feat/argos-*` dédiées | `visionhub/`, `tests/`, `docs/`, CI |

Partagé PPE + Behavior : `usecases/safety/config.yaml`, `usecases/safety/analyzer.py`, `usecases/safety/README.md`, `AGENTS.md` (bascule vers le composite par une PR commune).

---

## ARGOS AI Quality — branche `quality`

- **Entrées** : dataset qualité de la pièce de référence (hors dépôt), contrat `Analyzer`, `QualityDetails`, test de contrat.
- **Sorties** : `usecases/quality/analyzer.py` (vraie classe, imports lourds dans `load()`), `config.yaml` (classe, seuils, params), runs MLflow, `model-package.json`.
- **Livrables** : modèle YOLO26-cls + baseline OpenCV comparée ; split par séquence ; rapport d'évaluation (`recall_nok`, `false_reject_rate`, matrice de confusion, latence CPU) dans `usecases/quality/AGENTS.md`.
- **Tests d'acceptation** : `pytest tests/test_contract.py` vert avec le vrai modèle ; un cycle PLC (`plc_sim`) renvoie OK/NOK/HOLD avec `model_name`/`model_version` MLflow ; latence < 2 s CPU.
- **Dépendances** : MLOps (tracking, registry, package), Intégration (chargement du package sur l'Edge).
- **Démarrer** : `git fetch && git switch quality && git merge origin/main` (après fusion de la baseline) ; corriger l'extra `quality` de `pyproject.toml` (anomalib → ultralytics) par PR à l'Intégration.

## ARGOS AI PPE — branche `feat/ai-ppe`

- **Entrées** : `PPEDetector`, `PPEReport`, `PersonPPE`, `PersonPPEExtension` (`visionhub/integration/vision.py`) ; `MockBehaviorDetector` pour tester la composition.
- **Sorties** : `usecases/safety/ppe/detector.py` (classe `PPEDetector` conforme au protocole), `usecases/safety/ppe/tests/`, runs MLflow, `model-package.json`.
- **Livrables** : détection casque, gilet, lunettes, gants, chaussures (si visibles), état `uncertain` quand non vérifiable ; aucune identification, aucun visage stocké.
- **Tests d'acceptation** : `CompositeSafetyAnalyzer` avec votre détecteur + `MockBehaviorDetector` respecte le contrat safety (voir `tests/baseline/test_integration_contracts.py` comme modèle) ; métriques par classe dans MLflow.
- **Dépendances** : Behavior (config commune), MLOps, Intégration (extension `PersonPPE` : chaussures, écouteurs — accord collectif).
- **Démarrer** : `git switch -c feat/ai-ppe argos-baseline` ; créer `usecases/safety/ppe/__init__.py` et `detector.py`.

## ARGOS AI Behavior — branche `feat/ai-behavior`

- **Entrées** : `BehaviorDetector`, `BehaviorReport`, `BehaviorFinding`, `DangerZone` ; `MockPPEDetector` ; module `usecases/workstation`.
- **Sorties** : `usecases/safety/behavior/detector.py`, configuration des zones dangereuses par caméra, analyseur 5S (évolution de `usecases/workstation/analyzer.py`), runs MLflow, packages.
- **Livrables** : téléphone, écouteurs, main ou personne en zone dangereuse, comportements à risque (pose estimation, suivi temporel) ; écarts 5S par rapport à une référence (objets manquants, déplacés, en trop, encombrement).
- **Tests d'acceptation** : composite safety conforme au contrat ; `pytest tests/test_contract.py` vert pour `workstation` ; règles de zones testées sur images synthétiques.
- **Dépendances** : PPE (config commune), Intégration (regroupement des alertes en épisodes 02B, extension `SafetyDetails.findings`), MLOps.
- **Démarrer** : `git switch -c feat/ai-behavior argos-baseline`.

## ARGOS MLOps — branche `feat/argos-mlops`

- **Entrées** : contrats `visionhub/integration/mlops.py`, exemple `mlops/examples/model-package.example.json`, cluster A100, MLflow (autonome d'abord, Databricks si confirmé).
- **Sorties** : `mlops/` (pipelines DVC, entraînement, évaluation, export ONNX, enregistrement MLflow, génération du `model-package.json`, calcul des dérives), documentation d'installation.
- **Livrables** : serveur MLflow local reproductible ; pipeline de référence sur la qualité ; `ModelPackage` valide (`ModelPackage.model_validate_json(...)`) ; métriques de monitoring (`MonitoringMetrics`, PSI/KS) ; politique de réentraînement (jamais de déploiement sans approbation).
- **Tests d'acceptation** : un `model-package.json` produit par le pipeline se valide avec le contrat et son sha256 correspond à l'artefact ; un run MLflow contient params, métriques et artefacts.
- **Dépendances** : groupes IA (code d'entraînement), Intégration (distribution des packages aux Edge, API Core `/api/v1/models`), Frontend (écrans AI Leader).
- **Démarrer** : `git switch -c feat/argos-mlops argos-baseline` ; lire `mlops/README.md`. Ne pas modifier `visionhub/integration/mlops.py` sans PR à l'Intégration.

## ARGOS Frontend — branche `feat/argos-frontend`

- **Entrées** : squelette `frontend/`, types générés, fixtures, catalogue des endpoints (§5 des contrats).
- **Sorties** : les trois espaces (Opérateur, Superviseur, AI Leader) au design ARGOS (bleu nuit, cyan).
- **Livrables** : Opérateur (verdict, compteurs, objectif, cadence, alertes, signalement, correction avec motif) sur l'API **Edge** ; Superviseur (12 postes dont simulés signalés, graphiques, alertes, signalements) et AI Leader (modèles, déploiements, dérives, approbation, rollback) sur l'API **Core**.
- **Tests d'acceptation** : `npm run typecheck && npm test && npm run build` verts ; tout fonctionne en mode `mock` ; l'espace Opérateur fonctionne en mode `live` contre `visionhub.argos_app`.
- **Dépendances** : Intégration (endpoints 🛠️), MLOps (données AI Leader).
- **Démarrer** : `git switch -c feat/argos-frontend argos-baseline` ; `cd frontend && npm ci && npm run dev`. Ne jamais éditer `src/api/generated/` ni `src/mocks/fixtures/` à la main.

## Intégration (Edge/Core) — responsabilité transverse

Outbox et synchronisation, ARGOS Core (ingestion idempotente, PostgreSQL, agrégats multiposte, Alert Manager), endpoints 🛠️, anonymisation, séparation des sources caméra, chargement des `model-package.json` sur l'Edge, revue des PR touchant les contrats.
