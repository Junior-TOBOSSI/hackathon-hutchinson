# CORE-02 — liaison Production Engine → Core

Le Production Engine écrit chaque fait métier et son événement `argos.edge-event/1` dans **la même transaction SQLite Edge**. Un worker local expédie les événements vers `POST /ingest/v1/events`. Le Core accuse réception après avoir commis l'inbox, les projections et les alertes. Aucun appel réseau ne bloque un cycle PLC.

| Fait Edge | Événement d'outbox | Point d'écriture |
|---|---|---|
| Cycle avec inférence | `inference`, puis `part.recorded` | `ProductionStore.insert_part()` ; un cycle en erreur produit seulement `part.recorded`. |
| Correction humaine | `part.corrected`, avec `Correction.sequence` | `ProductionStore.add_correction()` ; le verdict prédit reste intact. |
| Disposition physique | `part.disposition` | `ProductionStore.set_disposition()` ; indépendante du verdict. |
| Ouverture / fermeture de shift | `shift.opened` / `shift.closed` | `ProductionStore.insert_shift()` / `close_shift()`. |

`POST /events/{id}/feedback` est historique et ne corrige pas une pièce. Utiliser `POST /production/parts/{id}/corrections`. L'Edge ne transmet ni image, ni visage, ni identité personnelle dans ces événements.

## Durabilité et reprise

La migration additive `edge_outbox` ajoute à la base Edge une ligne par événement avec `event_id`, séquence croissante par poste, contenu sérialisé, acquittement, tentatives et dernière erreur. L'insertion d'outbox fait partie du `BEGIN IMMEDIATE` du fait métier : si elle échoue, la pièce, la correction, la disposition ou le shift sont annulés avec elle. Le cycle rejoué avec le même `cycle_id` ne crée ni nouvelle pièce ni nouveaux événements.

Le worker envoie au plus 100 événements d'un même poste par lot, dans l'ordre. Il marque livrés seulement les résultats `accepted` et `duplicate` d'un `IngestAck` correspondant au lot. Un `rejected` reste conservé et visible dans `GET /edge/sync/status` pour investigation ; les événements suivants peuvent continuer. Après erreur HTTP, timeout ou ACK perdu, il rejoue les mêmes identifiants et contenus avec un délai croissant plafonné à 30 secondes. Le Core déduplique par `event_id` et `(station_id, edge_sequence)`. L'outbox n'est pas purgée automatiquement.

`ARGOS_CORE_URL` active le worker. Ce MVP accepte uniquement une origine HTTP sur `localhost`, `127.0.0.1` ou `::1`, car les services locaux n'ont pas d'authentification. Sans cette variable, les faits et l'outbox sont tout de même écrits ; la synchronisation reprend au démarrage suivant avec l'URL configurée. Il faut une base Edge persistante pour rejouer après redémarrage.

## Démarrer la chaîne locale (PowerShell)

Ouvrir trois terminaux dans `C:\Users\GDYZ5751\Desktop\ARGOS_CORE`. Choisir d'autres ports libres si nécessaire.

**Terminal Core :**

```powershell
$env:ARGOS_CORE_DB = "$PWD\var\argos-core.sqlite3"
.\.venv\Scripts\python.exe -m uvicorn visionhub.core.app:app --host 127.0.0.1 --port 8020
```

**Terminal Edge :**

```powershell
$env:DB_PATH = "$PWD\var\argos-edge.sqlite3"
$env:PIPELINE_ENABLED = 'false'
$env:ARGOS_CORE_URL = 'http://127.0.0.1:8020'
.\.venv\Scripts\python.exe -m uvicorn visionhub.argos_app:app --host 127.0.0.1 --port 18040
```

**Terminal simulateur PLC :**

```powershell
.\.venv\Scripts\python.exe -m visionhub.production.plc_sim --api-url http://127.0.0.1:18040 --station WS-01 --cycles 5 --interval 0.2 --duplicate-rate 0.3
Invoke-RestMethod http://127.0.0.1:18040/edge/sync/status
Invoke-RestMethod http://127.0.0.1:8020/health
Invoke-RestMethod http://127.0.0.1:8020/api/v1/stations/WS-01
Invoke-RestMethod http://127.0.0.1:8020/api/v1/alerts
```

Pour un KPI de shift, ouvrir d'abord un shift via `POST /production/stations/WS-01/shifts` avec `{"name":"demo","target_parts":5}`. Le frontend de supervision peut appeler `GET /api/v1/stations`, `/api/v1/stations/{id}`, `/api/v1/kpi`, `/api/v1/stations/{id}/kpi`, `/api/v1/alerts`, `/api/v1/parts` et `/api/v1/events`. `GET /edge/sync/status` sert au diagnostic de la liaison.

## Raccordement de l'adaptateur d'inférence de Claude

Brancher l'adaptateur au contrat `Analyzer` et à `usecases/quality/config.yaml` selon `docs/integration-contracts.md`. Conserver l'exécution normale de `ProductionEngine.run_cycle()` : elle appelle déjà l'analyseur enregistré et `ProductionStore.insert_part()`. L'adaptateur fournit le score brut (plus haut = pire), le nom et la version du modèle, et l'événement d'inférence existant. Le Production Engine enregistre alors la pièce et les événements `inference` / `part.recorded` dans l'outbox. Aucune modification de `visionhub/production/outbox.py`, `sync.py` ou du Core n'est requise. Tester un cycle PLC simulé après remplacement de l'analyseur, puis contrôler `/edge/sync/status`, `/api/v1/parts` et `/api/v1/stations/{id}/kpi`. Les images restent sur l'Edge ; le Core reçoit les métadonnées contractuelles.

Limites CORE-02 : les inférences Safety/Workstation hors cycles du Production Engine, les états équipement/modèle et les signalements opérateur n'ont pas encore de point d'écriture métier Edge commun à raccorder. Le worker suppose un seul processus Edge écrivain par base SQLite. L'API locale n'a ni authentification ni chiffrement réseau ; ne pas l'exposer directement à un autre hôte.
