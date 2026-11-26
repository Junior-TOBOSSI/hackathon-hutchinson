# ARGOS — Contrats d'intégration (ARGOS-BASELINE)

Référence commune des cinq groupes. Les contrats sont **du code** (Pydantic) ; ce document les explique. En cas d'écart, **le code fait foi**.

| Domaine | Code source | Schémas exportés |
|---|---|---|
| Inférence (historique, protégé) | `visionhub/contracts.py`, `visionhub/analyzer.py` | `frontend/openapi/edge.openapi.json` |
| Production Engine (Edge) | `visionhub/production/contracts.py` | `frontend/openapi/edge.openapi.json` |
| Vision PPE / Behavior | `visionhub/integration/vision.py`, `safety_composite.py` | `frontend/openapi/contracts.openapi.json` |
| Edge → Core | `visionhub/integration/edge_events.py` | idem |
| Core (lecture UI) | `visionhub/integration/core_api.py` | idem |
| MLOps | `visionhub/integration/mlops.py` | idem |

Après toute modification d'un contrat : `python -m visionhub.integration.export` puis `cd frontend && npm run gen:api`. Le test `tests/baseline/test_integration_contracts.py::test_exported_artifacts_are_up_to_date` échoue tant que ce n'est pas fait.

---

## 1. Architecture

```text
                 BUILD — ARGOS MLOps (DVC, MLflow, A100, Databricks à confirmer)
                          │ model-package.json (+ artefact ONNX/pt, sha256)
                          ▼
┌──────────── RUN — ARGOS Edge (1 par poste) ────────────┐        ┌──────── ARGOS Core ────────┐
│ caméras → pipeline → analyseurs → décision             │ outbox │ POST /ingest/v1/events     │
│ Production Engine (cycles, pièces, shifts, KPI)        │ ─────► │ PostgreSQL (cible)         │
│ SQLite (events, parts, shifts, corrections, outbox)    │  ACK   │ multiposte, KPI agrégés    │
│ API locale (8000) ◄── UI Opérateur                     │ ◄───── │ Alert Manager, MLOps       │
└────────────────────────────────────────────────────────┘        │ API /api/v1 ◄── UI Superv. │
                                                                  │                 UI AI Lead.│
                                                                  └────────────────────────────┘
```

L'inférence et le Production Engine **ne dépendent jamais** de Core, de MLflow ni de Databricks : un poste hors ligne continue de produire, d'afficher ses KPI et de stocker ses événements dans l'outbox.

---

## 2. Contrat Computer Vision (groupes AI Quality, AI PPE, AI Behavior)

### 2.1 Interface commune (inchangée)

```python
class Analyzer(ABC):              # visionhub/analyzer.py
    use_case: ClassVar[UseCase]   # quality | workstation | safety
    name: ClassVar[str]
    version: ClassVar[str]
    def load(self, config: dict) -> None: ...            # params YAML + "device"
    def analyze(self, image: np.ndarray, meta: FrameMeta) -> AnalysisResult: ...
```

| Élément | Règle |
|---|---|
| Image d'entrée | `np.ndarray` **BGR `uint8` (H, W, 3)** (convention OpenCV), déjà recadrée (`ROI`) ; ne pas la modifier en place |
| Métadonnées | `FrameMeta(frame_id, timestamp UTC, workstation_id, camera_id)` ; pour un cycle PLC, `frame_id = "cycle:<poste>:<cycle>"` |
| Score | `[0, 1]`, **plus haut = pire**. Renvoyer le score **brut** : la décision (`conforme` / `a_verifier` / `anomalie`) est prise par la couche commune avec deux seuils |
| Bounding boxes | **normalisées** `[0, 1]`, `x1 ≤ x2`, `y1 ≤ y2` (`BBox`) |
| `details` | `QualityDetails`, `WorkstationDetails` ou `SafetyDetails` selon le cas d'usage (champs inconnus refusés) |
| Erreurs | **Lever une exception** (jamais renvoyer un faux « conforme »). Le pipeline l'isole ; pour un cycle PLC la pièce devient `ERROR` |
| Dépendances lourdes | importées **dans `load()`** (ultralytics, torch, onnxruntime), sinon la CI casse |
| Latence | `analyze()` < 2 s sur CPU (test de contrat, `CONTRACT_MAX_SECONDS`) ; laisser `latency_ms = 0` |
| Version | `model_name` = nom du modèle enregistré dans MLflow (ex. `argos-quality`), `model_version` = numéro de version MLflow (ex. `"3"`). Les faux analyseurs gardent `fake-*` / `0.1.0` |
| Paramètres | `usecases/<cas>/config.yaml` : `analyzer_class`, `thresholds {low, high}`, `params` (passés à `load`) |
| Vie privée | aucune image, aucun visage, aucune identité dans les sorties ; `person_index` est un index **dans l'image**, pas un identifiant de suivi |

### 2.2 Quality (groupe AI Quality, branche `quality`)

- Pièce de référence : règle de conformité fournie par le client (document interne, hors dépôt). Classes : `["OK", "NOK"]`.
- `score` = probabilité NOK (ou 1 − P(OK)). `details = QualityDetails(zones=[...], heatmap_ref=None)` (zones facultatives).
- Images basse résolution : l'analyseur redimensionne lui-même ; le `ROI` global doit rester **vide** pour la qualité.
- Exécuté **uniquement** via les cycles PLC du Production Engine (et `POST /analyze`).
- Split **par séquence d'acquisition** obligatoire (`DatasetRef.split_strategy = "by_sequence"`).
- Métriques imposées : `recall_nok` (priorité : aucune pièce NOK chez le client), `false_reject_rate`, `accuracy`, matrice de confusion, latence CPU p50/p95.

### 2.3 Safety = PPE + Behavior (groupes AI PPE et AI Behavior)

Le registre garde **un seul** analyseur `safety`. Les deux groupes livrent un **détecteur** composé par `visionhub.integration.safety_composite:CompositeSafetyAnalyzer` :

```python
class PPEDetector(Protocol):        # AI PPE
    name: str; version: str
    def load(self, config: dict) -> None: ...
    def detect(self, image, meta) -> PPEReport: ...        # persons + extensions + score

class BehaviorDetector(Protocol):   # AI Behavior
    name: str; version: str
    def load(self, config: dict) -> None: ...
    def detect(self, image, meta) -> BehaviorReport: ...   # findings + score
```

Fusion : `score = max(ppe.score, behavior.score)` ; personnes issues du PPE ; un `BehaviorFinding(kind="phone_use", person_index=i)` met `phone=True` sur la personne `i`. `model_name = "<ppe>+<behavior>"`, `model_version = "<v_ppe>+<v_behavior>"`.

Activation (décision PPE + Behavior + intégration) dans `usecases/safety/config.yaml` :

```yaml
analyzer_class: visionhub.integration.safety_composite:CompositeSafetyAnalyzer
thresholds: {low: 0.4, high: 0.7}
params:
  ppe:      {detector_class: "usecases.safety.ppe.detector:PPEDetector", params: {weights: ...}}
  behavior: {detector_class: "usecases.safety.behavior.detector:BehaviorDetector", params: {...}}
```

Des détecteurs simulés (`MockPPEDetector`, `MockBehaviorDetector`) permettent à chaque groupe de travailler sans l'autre.

**Classes PPE** : `person`, `helmet`, `vest`, `glasses`, `gloves`, `safety_shoes` ; états `present` / `absent` / `uncertain` (une chaussure non visible = `uncertain`, jamais `absent`).

**Constats Behavior** (`BehaviorKind`) : `phone_use`, `earphones`, `hand_in_danger_zone`, `person_in_danger_zone`, `running`, `fall`, `unsafe_posture`, et pour le 5S : `clutter`, `missing_object`, `misplaced_object`, `unexpected_object`. Zones dangereuses : `DangerZone(zone_id, polygon normalisé ≥ 3 points, kind)` configurées par caméra.

**Interdits** : reconnaissance faciale, identification, émotions. Floutage des visages avant tout affichage ou export (anonymisation à implémenter par l'intégration, cf. §7).

### 2.4 Workstation / 5S

Le module `usecases/workstation` est **conservé** tel quel (cas d'usage `workstation`, `WorkstationDetails`). Rattachement proposé : groupe **AI Behavior** (à confirmer). Les constats 5S produits par Behavior (`clutter`, `missing_object`…) peuvent alimenter soit `WorkstationDetails` via l'analyseur workstation, soit le composite safety : à trancher par le groupe Behavior avec l'intégration.

### 2.5 Extension proposée de `visionhub/contracts.py` (accord collectif requis)

Ajouts **optionnels avec valeur par défaut** (rétrocompatibles, aucun champ supprimé) :

```python
class PersonPPE(Contract):
    ...
    safety_shoes: PPEState = PPEState.UNCERTAIN    # NOUVEAU
    earphones: bool = False                         # NOUVEAU

class SafetyDetails(Contract):
    ...
    findings: list[BehaviorFinding] = []            # NOUVEAU (déplacé depuis integration/vision.py)
```

Tant que cet ajout n'est pas validé, chaussures, écouteurs, zones et comportements **augmentent le score** mais ne sont **pas stockés** dans les événements.

### 2.6 Protocole d'évaluation (tous les groupes IA)

1. Jeu de données versionné (`DatasetRef`, DVC), split documenté ; **jeu de test jamais utilisé pour régler les seuils**.
2. Métriques loguées dans MLflow (`EvaluationMetrics`) : par classe, matrice de confusion, latence CPU p50/p95 sur la machine Edge cible.
3. Seuils recommandés (`recommended_thresholds`) justifiés par la courbe rappel / fausses alertes.
4. Le test de contrat passe avec le vrai modèle (`pytest tests/test_contract.py`).
5. Livraison sous forme de **`model-package.json`** (§4.2).

---

## 3. Contrat Edge → Core (`argos.edge-event/1`)

### 3.1 Enveloppe

| Champ | Description |
|---|---|
| `schema_version` | `"argos.edge-event/1"` (toute rupture = `/2`) |
| `event_id` | UUID, **clé d'idempotence** |
| `event_type` | `inference`, `part.recorded`, `part.corrected`, `part.disposition`, `shift.opened`, `shift.closed`, `operator.report`, `equipment.status`, `model.status` |
| `station_id`, `edge_sequence` | séquence **strictement croissante par poste** (ordre de l'outbox) |
| `occurred_at` | UTC avec fuseau |
| `simulated` | `true` pour les postes / cycles simulés |
| `camera_id`, `cycle_id`, `part_id`, `use_case`, `model_name`, `model_version`, `score`, `decision`, `verdict` | en-têtes d'indexation (facultatifs selon le type) |
| `payload` | union typée discriminée par `kind` ; doit correspondre à `event_type` |

Exemple complet : `frontend/src/mocks/fixtures/integration/edge-event-batch.json`.

### 3.2 Synchronisation (à développer par l'intégration)

- **Outbox SQLite** sur l'Edge (table `outbox(edge_sequence PK AUTOINCREMENT, event_id UNIQUE, payload, created_at, delivered_at, attempts, last_error, rejected)`), écrite **dans la même transaction** que le fait métier (pièce, correction…).
- Envoi par lots ordonnés (`EdgeEventBatch`, ≤ 500) vers `POST /ingest/v1/events` ; réessai avec backoff exponentiel plafonné ; l'outbox n'est **jamais** purgée d'un événement non acquitté.
- `IngestAck` : par événement `accepted` | `duplicate` (déjà reçu : traité comme livré) | `rejected` (gardé, signalé). `highest_contiguous_sequence` permet de détecter les trous.
- **Idempotence Core** : contrainte unique sur `event_id`.
- **Ordre des corrections** : `Correction.sequence` par pièce ; Core applique la plus haute séquence reçue → résultat correct quel que soit l'ordre d'arrivée.
- **Aucune image** de personne dans les événements (le contrat refuse les champs inconnus).

---

## 4. Contrats MLOps (groupe ARGOS MLOps)

### 4.1 Objets

`DatasetRef`, `TrainingConfig`, `TrainingJob`, `EvaluationMetrics`, `ModelRef` (`registered_model` + `version` MLflow, `alias`, `mlflow_run_id`, URI `models:/<nom>/<version>`), `ArtifactRef`, `ModelDeployment`, `StationDeploymentStatus`, `MonitoringMetrics` (+ `DriftMeasure`), `RetrainingPolicy`. **MLflow reste la source de vérité** des runs, versions et alias ; ARGOS ne stocke que des références. Noms Unity Catalog (`catalog.schema.model`) acceptés pour Databricks.

### 4.2 Livraison de modèle : `model-package.json`

Exemple : `mlops/examples/model-package.example.json`. Contenu : modèle (`ModelRef`), `analyzer_class`, `runtime` (`onnxruntime` | `ultralytics` | `torch` | `opencv`), `device`, artefact (URI, **sha256**, taille, format), prétraitement (taille, couleur, redimensionnement, normalisation), classes, seuils, paramètres, dataset, évaluation.

Règles : l'Edge **refuse** un paquet dont le sha256 ne correspond pas ; un déploiement passe toujours par `pending_approval` → `approved` (AI Leader) ; **aucun déploiement automatique** (`deployment_requires_approval` est toujours vrai) ; le rollback cible `previous_model`.

---

## 5. Catalogue des endpoints

Légende : ✅ implémenté · 🛠️ à développer · 🧪 simulé (mode mock frontend).

### Edge (un par poste, `visionhub.argos_app:app`, port 8000)

| | Méthode et route | Persona | Contrat |
|---|---|---|---|
| ✅🧪 | `GET /health`, `GET /use-cases`, `GET /events`, `GET /stats` | tous | historiques |
| ✅ | `POST /analyze`, `PUT /thresholds/{use_case}` | AI Leader / debug | historiques |
| ✅ | `POST /events/{id}/feedback` | historique (**pas pour les pièces**) | `FeedbackIn` |
| ✅ | `POST /production/stations/{id}/cycles` | PLC | `Part` |
| ✅🧪 | `GET /production/parts`, `GET /production/parts/{id}`, `GET /production/stations/{id}/cycles/{cycle}` | Opérateur | `Part` |
| ✅🧪 | `POST /production/parts/{id}/corrections`, `GET .../corrections` | Opérateur | `CorrectionIn`, `Correction` |
| ✅ | `PUT /production/parts/{id}/disposition` | process | `DispositionIn` |
| ✅🧪 | `POST /production/stations/{id}/shifts`, `GET .../shifts/current`, `POST /production/shifts/{id}/close`, `GET /production/shifts[/{id}]` | Opérateur | `Shift`, `ShiftReport` |
| ✅🧪 | `GET /production/stations/{id}/kpi` | Opérateur | `ProductionKPI` |
| 🛠️ | `POST /production/stations/{id}/reports` | Opérateur | `OperatorReportPayload` |
| 🛠️ | `GET /edge/sync/status` (outbox : en attente, dernier ACK) | Opérateur / intégration | à définir |

### Core (`/api/v1`, port 9000 en développement)

| | Méthode et route | Persona | Contrat |
|---|---|---|---|
| 🛠️ | `POST /ingest/v1/events` | Edge | `EdgeEventBatch` → `IngestAck` |
| 🛠️🧪 | `GET /api/v1/stations`, `GET /api/v1/stations/{id}` | Superviseur | `StationSummary` |
| 🛠️🧪 | `GET /api/v1/alerts`, `POST /api/v1/alerts/{id}/{acknowledge,validate,reject,resolve}` | Superviseur | `Alert` |
| 🛠️🧪 | `GET /api/v1/operator-reports` | Superviseur | `OperatorReport` |
| 🛠️🧪 | `GET /api/v1/models`, `GET /api/v1/deployments`, `POST /api/v1/deployments`, `POST .../{id}/approve`, `POST .../{id}/rollback` | AI Leader | `ModelPackage`, `ModelDeployment` |
| 🛠️🧪 | `GET /api/v1/monitoring`, `GET /api/v1/training-jobs`, `POST /api/v1/training-jobs`, `GET/PUT /api/v1/retraining-policies` | AI Leader | `MonitoringMetrics`, `TrainingJob`, `RetrainingPolicy` |

---

## 6. Frontend

`frontend/` : un seul React (Vite, TypeScript, Tailwind, TanStack Query, Plotly), trois espaces `/operator` (API **Edge**), `/supervisor` et `/ai-leader` (API **Core**). Types **générés** depuis les OpenAPI (`src/api/generated`, ne jamais éditer). Mode `mock` par défaut (fixtures validées) ; mode `live` via le proxy Vite (`/edge-api`, `/core-api`), sans CORS côté backends. Voir `frontend/README.md`.

## 7. Ce qui reste du ressort de l'intégration (Edge/Core)

Outbox et synchronisation, Core (ingestion, PostgreSQL, agrégats, Alert Manager 02B, gestion des postes 02C), `POST /production/.../reports`, anonymisation des visages (`preprocess.anonymize`), séparation des sources caméra par cas d'usage, branchement définitif de `install_production` dans `api.py` (accord collectif).
