# DBX-PERF-01 — Performance de l'espace AI Leader

## 1. Diagnostic

| Cause | Effet mesuré |
|---|---|
| MLflow résout les identifiants Databricks **à chaque requête** (`get_databricks_host_creds` : nouveau `WorkspaceClient`, requête `/.well-known/databricks-config` puis un processus CLI `databricks auth token`) | ≈ 2,3 s par appel MLflow, à froid comme à chaud ; 13 à 28 processus CLI pour une vue d'ensemble |
| Lectures redondantes : `overview` recalcule le statut que `status` calcule en parallèle, et lit deux fois le même run | 15 appels Databricks pour `overview` |
| Frontend : `useSelection` attendait le statut de tous les modèles avant d'afficher Registry, Training, Datasets et Monitoring | Écran de chargement global d'environ 10 s |
| Frontend : « Dernier entraînement » attendait `experiments`, puis `runs` | Chaîne de 8 s |
| Frontend : une promesse obsolète pouvait écraser une réponse plus récente ; « Actualiser » vidait tout le cache ; aucun délai d'expiration | Données périmées possibles, indicateurs « … » sans fin |
| Délais par défaut : MLflow 120 s par requête avec jusqu'à 500 s de nouvelles tentatives ; SDK Databricks 60 s avec jusqu'à 300 s | Panne Databricks = attente de plusieurs minutes |

## 2. Mécanismes

### Backend (`mlops/`)

- **`databricks/auth_cache.py`** réutilise pendant 10 minutes les identifiants calculés par MLflow.
  - Seuls les identifiants *sans jeton* sont gardés (chemin SDK : hôte, profil, identifiant du workspace). Le jeton OAuth reste dans le `WorkspaceClient` que MLflow garde en cache, et ce client le renouvelle lui-même.
  - Un échec n'est jamais mis en cache.
  - Un cache par store (donc par profil et par workspace).
  - Une seule résolution à la fois.
  - Rien n'est écrit dans les logs.
  - **Dépendance aux attributs internes de MLflow 3.18** : `MlflowClient._tracking_client.store.get_host_creds` et `_get_registry_client().store.get_host_creds` / `get_tracking_host_creds`. Si ces attributs sont absents, rien n'est installé et MLflow garde son comportement par défaut : plus lent, mais correct. Un test construit un vrai `MlflowClient` pour vérifier cette compatibilité.
- **`databricks/read_cache.py`** est un cache en mémoire (aucune dépendance) :
  - TTL de 60 s pour l'état courant, 1 h pour un run MLflow terminé ;
  - déduplication des requêtes simultanées ;
  - **générations** : une lecture démarrée avant une mutation ne peut pas réécrire le cache ;
  - une erreur ne remplace jamais la dernière valeur valide ; si Databricks est injoignable, celle-ci est servie et marquée `stale` ;
  - budget de temps cumulé par requête : 25 s.
- **En-têtes** `X-HOVIS-Fetched-At` (fin de la lecture Databricks **réelle**, la plus ancienne si la réponse en combine plusieurs) et `X-HOVIS-Cache` (`miss` = lu à l'instant, `hit`, `mixed`, `stale`). `?fresh=true` force une relecture. `health` interroge toujours Databricks en direct, sans en-tête.
- **Mutations** (approbation, alias, déclenchement d'un job) :
  - le cache concerné est invalidé avant et après l'écriture ;
  - l'existence de la version est vérifiée dans le registre réel ;
  - l'état renvoyé est relu à neuf.

  Elles n'ont pas de budget global, pour ne pas s'arrêter entre deux écritures. Elles restent bornées par les délais de chaque requête.
- **Délais.**
  - SDK : 15 s par requête, 30 s de nouvelles tentatives au plus (`build_workspace_client`).
  - MLflow : 15 s par requête, 2 tentatives, 30 s de nouvelles tentatives au plus (variables posées pour ce processus uniquement).
- **Préchauffage** (`HOVIS_MLOPS_WARMUP=1`, activé par `start_argos_live.ps1`) : un thread en tâche de fond effectue les mêmes lectures que la vue d'ensemble.
  - Il ne fait que des lectures de configuration (registre, serving, jobs, tracking, état du warehouse) : aucun job, aucune inférence, aucun démarrage du warehouse.
  - Il ne bloque jamais le démarrage, et ses erreurs sont seulement écrites dans les logs.

### Frontend (`argos-ui/src/pages/ai-leader/`, `src/api/mlops.ts`)

- **`store.ts`** (sans React, testé avec `node --test`) :
  - génération par ressource : une réponse obsolète est ignorée ;
  - la dernière donnée reste affichée pendant une actualisation ;
  - une erreur est affichée à côté de la dernière donnée valide, sans la remplacer ;
  - délai d'expiration de 30 s (supérieur au budget backend de 25 s) ;
  - « Actualiser » relit (`fresh`) uniquement les ressources affichées ; les autres sont relues à l'ouverture de leur section ; pas de second envoi pendant une actualisation.
- Plus d'attente globale : la liste des modèles (configuration) ne dépend plus du statut, chaque bloc attend sa propre donnée. « Dernier job d'entraînement » vient de `/jobs`.
- **Fraîcheur affichée** pour ce qui est **à l'écran** : intervalle des dates de lecture réelles, origine (lecture directe, cache serveur, dernier résultat connu), actualisation en cours. Une lecture en cache n'est jamais présentée comme une lecture en direct.

## 3. Mesures HTTP

Ces mesures portent sur le parcours HTTP de la vue d'ensemble, rejoué en parallèle comme le ferait un navigateur. **Ce ne sont pas des mesures faites dans le navigateur** : DevTools est bloqué par l'administration du poste. Le comptage des appels a été fait dans chaque processus par un lanceur de mesure, placé dans le scratchpad et non versionné.

| Situation | Premiers indicateurs | Vue d'ensemble complète | Appels Databricks | Processus CLI |
|---|---|---|---|---|
| Avant, à froid | 8,8 s | 37,1 s | 49 | 28 |
| Avant, à chaud | 1,7 s | 21,5 s | 40 | 13 |
| Après, à froid sans préchauffage | 5,6 s | 13,5 s | 26 | 6 |
| Après, première vue après préchauffage (17 à 18 s en tâche de fond, passerelle disponible en 0,1 s) | 0,26 s | 0,29 s | 2 | 0 |
| Après, avec cache | 0,26 s | 0,26 s | 1 (`health`) | 0 |
| Après, cache expiré (62 s) | 0,47 s | 1,7 s | 17 | 0 |
| Après, actualisation forcée (`fresh=true`) | 0,49 s | 2,3 s | 25 | 0 |

Par endpoint (avant, à chaud → après, avec cache) :

| Endpoint | Avant | Après |
|---|---|---|
| `models/overview` | 18,5 à 21,5 s | 0,01 s (2,3 s en lecture forcée) |
| `mlops/models/{id}/status` | 10 à 13 s | 0,01 s (2,1 s en lecture forcée) |
| `experiments` | 3,0 s | 0,01 s |
| `runs` | 3 à 5 s | < 0,3 s |
| `jobs` | 1,8 à 3,0 s | 0,01 s |
| `endpoints` | 0,5 à 1,6 s | 0,01 s |

Les objectifs sont atteints dans tous les cas sauf un : **à froid sans préchauffage, 13,5 s** (contre 37,1 s avant). Ce temps vient de l'initialisation des clients et de la première résolution d'identifiants de chaque store MLflow (6 processus CLI). Le préchauffage le supprime pour l'utilisateur.

## 4. Tests

- `mlops/tests/test_perf_cache.py` (Databricks simulé) :
  - renouvellement des identifiants après le TTL ;
  - identifiants porteurs de jeton jamais mis en cache ;
  - échec d'authentification non mis en cache ;
  - aucune fuite dans les logs ;
  - stores isolés ;
  - compatibilité avec MLflow ;
  - vrai client SDK avec délais bornés ;
  - TTL et expiration ;
  - 10 requêtes simultanées pour 1 lecture distante ;
  - `fresh` ;
  - lecture démarrée avant une mutation ;
  - erreur qui n'écrase pas la dernière valeur ;
  - budget ;
  - invalidation et relecture après approbation et changement d'alias ;
  - Databricks indisponible (dernière valeur marquée `stale`, ou 503 rapide) ;
  - préchauffage qui ne lève jamais d'exception.
- `argos-ui/tests/ai-leader-store.test.ts` (`node --test argos-ui/tests/ai-leader-store.test.ts`) :
  - réponses dans le désordre ;
  - actualisations successives ;
  - échec d'une seule ressource ;
  - délai d'expiration ;
  - changement de modèle ;
  - ressources masquées ;
  - fraîcheur combinée.

## 5. Recette

1. `powershell -ExecutionPolicy Bypass -File mlops\scripts\start_argos_live.ps1`, ou les services déjà lancés (8020 et 5174).
2. Ouvrir http://127.0.0.1:5174, se connecter en AI Leader, puis vérifier :
   - la navigation est immédiate ;
   - les indicateurs apparaissent un par un ;
   - la barre affiche « Lu à … · cache serveur » ou « lecture directe ».
3. Cliquer sur « Actualiser » : les données restent affichées, la mention « actualisation… » apparaît, et le bouton est désactivé jusqu'à la fin.
4. Changer de section et de modèle rapidement : aucun chargement ne reste bloqué.
