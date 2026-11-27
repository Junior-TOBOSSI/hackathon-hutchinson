# INT-MLOPS-02 — intégration locale Monitoring

Base : `feat/mlops-unified` avec le checkpoint INT-DATA-02 `855545f`, puis merge
local du commit stable `2909af0` et de ses ancêtres `085d7ea`, `f96c829`.
Les travaux DBX-08 ne sont pas inclus.

## Modules

Une instance HOVIS expose Datasets, Training Factory, Model Registry,
Deployment Center et Monitoring sur `/ai-leader`. Le Package Builder et le
checkpoint Quality/Workstation restent présents. Le mode live exige
`VITE_LIVE_AI_LEADER=true` et le proxy `/api` vers la passerelle intégrée.

## Sources et limites du rapprochement

Monitoring lit les stations, événements et pièces via l'API Core, et les
évaluations hors ligne via MLflow en lecture. Les données simulées restent
signalées et filtrables. Le journal local de Deployment est désormais lu en
lecture seule dans le bloc `deployment` de `/api/mlops/overview/v2` : il expose
le nombre d'opérations Databricks Serving par statut. Le bloc est `partial`
car ces opérations ne donnent pas les versions souhaitées par poste Edge.
Le statut `StationDeploymentStatus` du Core décrit la version effectivement
chargée si un événement `model.status` a été reçu. Une inférence ne porte pas
encore une référence exacte du package et ne peut donc pas être reliée
automatiquement à une version Unity Catalog. Monitoring conserve la clé
`unassociated:*` pour éviter une association trompeuse par nom.

Le jeu Quality de 839 images est audité localement, sans splits définitifs
avant `tri_nok.csv`. Les quatre jeux Workstation sont toujours attendus ; le
code scientifique original est sauvegardé dans le checkpoint INT-DATA-02.

## Recette isolée

Dans PowerShell, depuis la racine du worktree :

```powershell
$env:ARGOS_CORE_DB="$env:USERPROFILE\ARGOS_MLOPS_LOCAL\unified\core.sqlite3"
$env:ARGOS_MLOPS_HOME="$env:USERPROFILE\ARGOS_MLOPS_LOCAL\unified"
$env:HOVIS_CORE_URL='http://127.0.0.1:8031'
$env:HOVIS_TRAINING_REMOTE='0'
$env:HOVIS_MLOPS_WARMUP='0'
& "$env:USERPROFILE\ARGOS_MLOPS_LOCAL\.venv\Scripts\python.exe" -m uvicorn mlops.api.platform:app --host 127.0.0.1 --port 8031
```

Dans un autre PowerShell, depuis `argos-ui` :

```powershell
$env:ARGOS_API_TARGET='http://127.0.0.1:8031'
$env:VITE_LIVE_AI_LEADER='true'
$env:VITE_LIFECYCLE_READ_ONLY='true'
$env:NODE_OPTIONS='--max-old-space-size=768'
npm run dev -- --host 127.0.0.1 --port 5177 --strictPort
```

Ouvrir `http://127.0.0.1:5177/ai-leader`. Les routes Monitoring sont sous
`/api/mlops/monitoring/*` et la synthèse des six sources sous
`/api/mlops/overview/v2`. La collecte et le gel d'une référence sont des POST
locaux et ne font pas partie de cette recette en lecture seule.
