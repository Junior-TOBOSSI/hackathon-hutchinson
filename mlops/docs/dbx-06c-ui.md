# DBX-06C — Registre des modèles et centre de déploiement

## Raccordement réel

Les deux pages reprennent la grille, les cartes KPI, les filtres, le tableau et les onglets de
DBX-04-FINAL. Le registre ouvre le catalogue global sans sélectionner de modèle. Un clic ouvre
un panneau 38/62. Le centre de déploiement possède son propre catalogue et son propre historique.
Les états d'approbation, d'alias UC et de Serving restent visuellement séparés.

| Vue | Source | Particularité |
|---|---|---|
| Familles et versions | `GET /api/mlops/models`, puis `GET /api/mlops/models/{id}/status` | Périmètre : modèles configurés dans HOVIS, sans famille fictive. Nouveau candidat affiché dès qu'il figure dans `ARGOS_DBX_MODELS_FILE` et que son statut UC est lisible. |
| Runs, métriques et lignage | `GET /api/mlops/runs/{id}` | Chargés après sélection du détail ; comparaison de versions seulement dans son onglet. Une métrique absente reste absente. |
| Décisions motivées | Routes `/api/mlops/registry/{id}/versions/{v}/decisions` de DBX-06B | Historique local durable, statut UC relu après action. Auteur et rôle déclarés, identité authentifiée indisponible. |
| Alias champion | `POST /api/models/{id}/promote` | Action distincte avec confirmation, seulement pour une version approuvée. |
| Cibles Cloud | `GET /api/mlops/endpoints` | Seuls les endpoints associés aux modèles HOVIS sont dans le catalogue. Mutation limitée à `argos-quality-poc` par DBX-06B. |
| Cibles Edge | `GET /api/v1/stations` | Lecture seule des statuts Core ; aucune distribution de modèle, aucun succès Edge simulé. |
| Opérations | `GET /api/mlops/deployments`, `GET /api/mlops/deployments/{id}`, `GET .../{id}/events` | SQLite DBX-06B ; état vide réel si aucune opération. Le suivi interroge seulement l'opération ouverte. |
| Assistant | `POST .../prepare`, `POST .../{id}/confirm`, `POST .../rollback/prepare` | Préparation, contrôle, confirmation exacte ; backend relit directement les conditions avant la mutation. |

La comparaison affiche seulement les valeurs enregistrées : exactitude, précision, rappel,
F1, faux rejets, défauts manqués et latence, selon leurs clés MLflow. Elle signale une différence
de dataset, protocole ou stratégie de split. Si ces métadonnées manquent, la comparabilité reste
non vérifiable. Une matrice n'est dessinée que si TP, TN, FP et FN existent pour le split choisi.
Les liens de run ouvrent sa réponse HOVIS. Si le run déclare un identifiant de famille dataset,
le lien ouvre directement cette famille et sa version ; sinon il ouvre le catalogue avec cette
limite clairement indiquée.
L'API actuelle ne liste pas les fichiers d'artefact individuels : l'onglet affiche l'URI de source
et les références disponibles sans inventer de contenu.
Les compteurs d'opérations portent sur les 500 dernières lignes chargées par l'API ; au-delà,
une pagination ou des agrégats backend seraient nécessaires.

## Prévisualisation indépendante, connectée en lecture seule

Ces commandes utilisent les ports **8024** et **5176** et deux bases locales dédiées. Elles ne
redémarrent aucun service existant. Dans le premier terminal PowerShell :

```powershell
$root = Join-Path $env:USERPROFILE 'Desktop\HOVIS_DEPLOYMENT'
$py = Join-Path $env:USERPROFILE 'ARGOS_MLOPS_LOCAL\.venv\Scripts\python.exe'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:MLFLOW_DISABLE_AGENT_HINT = '1'
$previewDir = Join-Path $env:USERPROFILE 'ARGOS_MLOPS_LOCAL\preview-dbx06c'
New-Item -ItemType Directory -Path $previewDir -Force | Out-Null
$env:ARGOS_CORE_DB = Join-Path $previewDir 'core.sqlite3'
$env:HOVIS_DEPLOYMENT_DB = Join-Path $previewDir 'operations.sqlite3'
Set-Location $root
& $py -m uvicorn mlops.api.platform:app --host 127.0.0.1 --port 8024
```

Dans le second terminal :

```powershell
Set-Location (Join-Path $env:USERPROFILE 'Desktop\HOVIS_DEPLOYMENT\argos-ui')
$env:ARGOS_API_TARGET = 'http://127.0.0.1:8024'
$env:VITE_USE_MOCK = 'true'
$env:VITE_LIVE_AI_LEADER = 'true'
$env:VITE_LIFECYCLE_READ_ONLY = 'true'
$env:NODE_OPTIONS = '--max-old-space-size=512'
npm run dev -- --host 127.0.0.1 --port 5176 --strictPort
```

Ouvrir `http://127.0.0.1:5176/ai-leader?section=registry` puis
`http://127.0.0.1:5176/ai-leader?section=deployment`. Le drapeau de prévisualisation désactive
les boutons de décision, promotion, préparation, confirmation et rollback dans ces pages. Le
backend reste une API fonctionnelle : la recette connectée n'envoie que des requêtes GET.
La connexion de démonstration utilise `a.noui@hutchinson.com` (mot de passe non vérifié en mode
mock) ; seul l'espace AI Leader lit les données Databricks réelles dans cette configuration.

Lectures de contrôle possibles :

```powershell
Invoke-RestMethod 'http://127.0.0.1:8024/api/mlops/models'
Invoke-RestMethod 'http://127.0.0.1:8024/api/mlops/models/quality-poc/status?fresh=true'
Invoke-RestMethod 'http://127.0.0.1:8024/api/mlops/endpoints?fresh=true'
Invoke-RestMethod 'http://127.0.0.1:8024/api/mlops/deployments'
Invoke-RestMethod 'http://127.0.0.1:8024/api/v1/stations'
```

## Limites et coordination

- Le catalogue découvre les familles par `ARGOS_DBX_MODELS_FILE` ou la configuration MLOps par
  défaut. Une version enregistrée par Claude apparaît sans changement d'interface dès que sa
  famille est ajoutée à cette configuration et que la passerelle est relancée. Une découverte UC
  de tous les modèles du workspace n'est pas implémentée, car le périmètre demandé est celui géré
  par HOVIS.
- Les contrôles Serving et la compatibilité réelle de rollback restent du ressort du backend
  DBX-06B. Le bouton Rollback apparaît seulement pour un déploiement vérifié dont la version
  précédente est encore approuvée et la version demandée visible comme active ; la préparation
  relit et peut encore refuser une configuration modifiée.
- Une préparation abandonnée reste dans le journal jusqu'à expiration (10 minutes). Son détail
  permet de reprendre la confirmation sans soumettre deux fois la même demande.
- `argos-ui/src/pages/ai-leader/common.tsx` (libellés et sélecteur) et
  `AiLeaderWorkspace.tsx` (ouverture globale du registre) sont les deux petits points partagés
  à vérifier avec Claude. Les pages Training Factory et Datasets n'ont pas été modifiées.

Tests locaux depuis `argos-ui` : `node --test tests/ai-leader-store.test.ts tests/lifecycle-catalog.test.ts tests/deployment-client.test.ts`, `npm run build` ; depuis la racine : `ruff check .` et
`pytest tests/test_contract.py` ; toutes les mutations sont exercées par une doublure `fetch`,
jamais contre Databricks.
