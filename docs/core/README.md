# ARGOS Core — CORE-01 et CORE-02

Service central local de supervision. Il **ne lance aucune inférence** et ne contacte ni Databricks, ni MLflow, ni un service externe. Il accepte les événements Edge conformes à `argos.edge-event/1`, conserve l'inbox dans une base SQLite distincte, et restitue des vues multipostes. Depuis CORE-02, le Production Engine alimente automatiquement cette inbox par une outbox SQLite et un worker HTTP local ; voir [edge-integration.md](edge-integration.md) pour les trois commandes de démarrage.

## Architecture

```text
Edge ou simulateur → POST /ingest/v1/events → transaction SQLite
                                       ├── inbox events (faits immuables)
                                       ├── projections station / parts / shifts / equipment / models / reports
                                       └── épisodes d'alerte
Supervisor → /api/v1/stations, /api/v1/kpi, /api/v1/alerts, /api/v1/events
```

Fichiers : `visionhub/core/store.py` (schéma, ingestion, projections, KPI, alertes), `app.py` (routes FastAPI), `simulator.py` (faits synthétiques bornés). Les modèles Pydantic existants restent dans `visionhub/integration/` et `visionhub/production/contracts.py`. Le calcul KPI réutilise `visionhub/production/kpi.py`.

## Démarrage et vérification (PowerShell)

```powershell
Set-Location 'C:\Users\GDYZ5751\Desktop\ARGOS_CORE'
$env:ARGOS_CORE_DB = 'C:\Users\GDYZ5751\Desktop\ARGOS_CORE\var\argos-core.sqlite3'
.\.venv\Scripts\python.exe -m uvicorn visionhub.core.app:app --host 127.0.0.1 --port 8020
```

Dans un **second terminal** :

```powershell
Set-Location 'C:\Users\GDYZ5751\Desktop\ARGOS_CORE'
.\.venv\Scripts\python.exe -m visionhub.core.simulator --api-url http://127.0.0.1:8020 --stations 12 --cycles 8 --seed 41
Invoke-RestMethod http://127.0.0.1:8020/health
Invoke-RestMethod http://127.0.0.1:8020/api/v1/stations
Invoke-RestMethod http://127.0.0.1:8020/api/v1/kpi
Invoke-RestMethod http://127.0.0.1:8020/api/v1/alerts
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
git status --short --branch
```

Arrêter le serveur avec **Ctrl+C dans son terminal**. Le simulateur se termine seul. Le serveur n'écoute que sur `127.0.0.1` dans cet exemple ; il n'a **aucune authentification** et ne convient pas tel quel à un réseau industriel.

La base est créée automatiquement au chemin `ARGOS_CORE_DB` (défaut `var/argos-core.sqlite3` depuis le répertoire courant). Le Core utilise `BEGIN IMMEDIATE`, un seul écrivain protégé par verrou, `synchronous=FULL`, une contrainte unique sur `event_id` et sur `(station_id, edge_sequence)`. L'inbox, les projections et les nouvelles observations d'alerte sont commises dans la même transaction. Si la transaction échoue, la route répond `503` et ne renvoie **aucun ACK**. À chaque démarrage, les projections sont reconstruites depuis l'inbox ; les épisodes et leurs statuts manuels restent enregistrés. Cette reconstruction par poste est volontairement simple et coûte O(nombre d'événements du poste) à chaque lot accepté : adaptée à la démonstration, à réévaluer pour un grand historique.

## Routes disponibles

| Route | Réponse | Note |
|---|---|---|
| `GET /health` | Compteurs `stations`, `events`, `parts` | Local uniquement. |
| `POST /ingest/v1/events` | `IngestAck` | `accepted`, `duplicate` ou `rejected` par événement valide ; lot Pydantic invalide : `422`. |
| `GET /api/v1/stations[/{id}]` | `StationSummary` | `online` si dernier événement horodaté dans les 120 s ; `name` = ID et `cell` = préfixe de l'ID faute de référentiel de postes. |
| `GET /api/v1/kpi`, `GET /api/v1/stations/{id}/kpi` | `ProductionKPI` | Fenêtre `[from, to)`, UTC ; défaut huit heures. Le KPI global compte les pièces puis calcule les taux, sans moyenne de pourcentages. |
| `GET /api/v1/alerts` | `Alert[]` | Filtres `status`, `station_id`. |
| `POST /api/v1/alerts/{id}/{acknowledge,validate,reject,resolve}` | `Alert` | Statuts persistés ; transitions invalides : `409`. Aucune résolution automatique. |
| `GET /api/v1/events`, `GET /api/v1/parts` | `EdgeEvent[]`, `Part[]` | Historique borné à 500 résultats par appel. |
| `GET /api/v1/operator-reports` | `OperatorReport[]` | Rapports reçus via ingestion. |
| `GET /api/v1/stations/{id}/model-status` | Payloads `ModelStatusPayload[]` | Préserve les versions Edge non numériques que `ModelRef` ne peut pas représenter. |

Les routes MLOps de `/api/v1/models`, `/deployments`, `/monitoring`, `/training-jobs` et `/retraining-policies` pourront être montées plus tard sur cette application par le chantier MLOps. Le Core industriel ne les implémente pas et ne renvoie pas de succès fictif.

## Règles des projections et limites

- Une pièce n'existe que par `part.recorded`. Une `inference` isolée n'augmente pas la production. `predicted_verdict` reste inchangé ; la correction de plus haute `sequence` donne `effective_verdict`. La disposition reste indépendante. `ERROR` ne devient jamais `OK` par défaut.
- Le Core peut recevoir une correction avant sa pièce. Elle reste dans l'inbox ; la reconstruction l'applique à l'arrivée de la pièce. Les événements d'état équipement et modèle les plus récents selon `occurred_at` gagnent. Un shift fermé ne redevient pas ouvert par arrivée tardive de son ouverture.
- `highest_contiguous_sequence` part de **1**. Si le premier événement reçu a la séquence 101, l'ACK indique 0 jusqu'à réception des séquences antérieures. Les trous ne font pas perdre les événements déjà acceptés.
- `StationSummary.models` utilise `ModelRef` seulement pour une version numérique. Une version locale comme `0.1.0` reste visible dans `/model-status`, sans fausse référence Registry.
- Les alertes du MVP proviennent des décisions non conformes, des pièces NOK/HOLD/ERROR, des équipements dégradés et des signalements. Elles regroupent les observations de même poste, caméra, cas d'usage et type jusqu'à une action manuelle terminale. Ces règles sont **de démonstration**, sans politique industrielle validée. Le paramètre `create_app(alert_on_review=False)` désactive les alertes pour les décisions `a_verifier` ; il ne supprime pas les alertes de pièces HOLD. Une nouvelle observation après résolution ouvre un nouvel épisode ; l'absence d'observation ne résout rien.
- Les objectifs ne sont exposés que pour un shift, dont les dates et la cible sont connues. Le KPI global ne fabrique pas d'objectif en mélangeant des shifts différents. `nok_rate` n'est pas un taux de rebut physique.
- Le simulateur génère des **verdicts synthétiques** ; ses versions de modèles sont fictives. Il démontre la chaîne événementielle, pas la précision d'un modèle. Chaque lancement produit de nouveaux identifiants de cycles ; le rejeu exact est effectué dans le même lancement.
- Une vue en ligne fondée sur `occurred_at` reste une approximation tant qu'aucun heartbeat Edge signé et aucune synchronisation de l'horloge des postes n'existent. L'API ne possède pas de gestion d'accès.

Voir [edge-integration.md](edge-integration.md) pour le raccordement transactionnel opérationnel et [frontend-mapping.md](frontend-mapping.md) pour les écrans.
