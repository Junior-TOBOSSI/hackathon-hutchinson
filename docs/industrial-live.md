# HOVIS INT-01 — interfaces industrielles en direct

## Périmètre

`VITE_LIVE_INDUSTRIAL=true` raccorde uniquement Operator, Supervisor, Cellule et
PosteDetail aux API existantes. Le login, Admin et les autres espaces conservent leur
mode actuel. Ce drapeau est indépendant de `VITE_USE_MOCK` et de
`VITE_LIVE_AI_LEADER`. Le frontend ne lit aucune base SQLite et n'appelle ni modèle
ni Databricks. Il utilise `/api/v1/*` pour le Core et `/production/*` pour l'Edge.
Depuis INT-01-FIX, les modes mock et live utilisent les **mêmes quatre pages et
les mêmes composants graphiques**. Le drapeau choisit la source de données.

L'écran Operator lit la dernière pièce dans l'Edge, les KPI, le shift, les alertes
et les équipements dans le Core. Une correction part vers
`POST /production/parts/{part_id}/corrections` avec verdict attendu, motif et
indicateur d'inspection physique. Le Core la reçoit ensuite par l'outbox Edge.
Supervisor affiche les 12 postes, les KPI globaux et par poste, les alertes et les
équipements du Core. Ses actions d'alerte utilisent l'API Core. Cellule et
PosteDetail lisent les postes réellement connus du Core. Operator et Cellule
rafraîchissent environ toutes les 2 s, Supervisor toutes les 4 s, PosteDetail
toutes les 5 s.

L'état « en ligne » représente la fraîcheur du dernier événement, pas une
télémétrie PLC permanente. Les observations Safety et Workstation de SIM-01 sont
marquées synthétiques. Une donnée absente reste inconnue. L'historique détaillé
montre au maximum 100 pièces et 100 événements par poste : ce n'est pas un
historique exhaustif. Le KPI standard porte sur les huit dernières heures ; seul
un shift actif fournit un objectif. Image, nombre de joints, signalement
opérateur transactionnel et notification maintenance restent indisponibles.
Les emplacements correspondants restent visibles avec « indisponible » ou
« inconnu ». La jauge continue « Heure par heure » d'Operator utilise le
rapport du shift actif transmis au Core, ou le dernier rapport de shift de
l'Edge lorsqu'il est clos. Sa graduation du bas répartit l'objectif total
selon la durée planifiée ; le remplissage suit les pièces **bonnes** et le
trait fin montre le temps écoulé. Un retard jusqu'à 10 % de l'attendu est
orange, au-delà il est rouge. Un shift clos conserve sa valeur finale.
Les graphiques horaires de Supervisor sont construits depuis les pièces Core
uniquement lorsque la liste plafonnée à 500 éléments est complète. Si cette
limite est atteinte, ils restent affichés avec un état indisponible. Le Core
ne fournit pas de ligne industrielle : l'atelier affiche « Ligne non
configurée » et les cellules réellement signalées par les postes. La bande
chronologique d'un shift clos n'est pas reconstruite sans historique de shift.

## Démarrage isolé en PowerShell

Depuis `C:\Users\GDYZ5751\Desktop\HOVIS_INDUSTRIAL`, installer une fois :

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
cd argos-ui
npm ci
cd ..
New-Item -ItemType Directory -Force var\industrial | Out-Null
```

Dans quatre terminaux distincts depuis la racine de ce worktree :

```powershell
# Terminal Core — base propre, port 8021
$env:ARGOS_CORE_DB = "$PWD\var\industrial\core.sqlite3"
.\.venv\Scripts\python.exe -m uvicorn visionhub.core.app:app --host 127.0.0.1 --port 8021
```

```powershell
# Terminal Edge — une seule instance écrivain sur cette base, port 18041
$env:DB_PATH = "$PWD\var\industrial\edge.sqlite3"
$env:PIPELINE_ENABLED = 'false'
$env:SOURCE = 'synthetic'
$env:ARGOS_CORE_URL = 'http://127.0.0.1:8021'
.\.venv\Scripts\python.exe -m uvicorn visionhub.argos_app:app --host 127.0.0.1 --port 18041
```

```powershell
# Terminal HOVIS — depuis argos-ui, port 5175
cd argos-ui
$env:VITE_USE_MOCK = 'true'
$env:VITE_LIVE_INDUSTRIAL = 'true'
$env:ARGOS_API_TARGET = 'http://127.0.0.1:8021'
$env:ARGOS_EDGE_TARGET = 'http://127.0.0.1:18041'
npm run dev -- --host 127.0.0.1 --port 5175 --strictPort
```

```powershell
# Terminal simulation — run-id neuf à chaque essai
.\.venv\Scripts\python.exe scripts/argos_demo.py --mode connected --core-url http://127.0.0.1:8021 --edge-url http://127.0.0.1:18041 --scenario full --stations 12 --direct-stations 2 --duration 60 --rate 2 --run-id JURY0001
```

En mode raccordé à la passerelle intégrée, changer **seulement**
`ARGOS_API_TARGET` vers `http://127.0.0.1:8020` et fournir explicitement
l'URL de l'Edge existant via `ARGOS_EDGE_TARGET`. Pointer ensuite le simulateur
sur ces deux mêmes origines avec `--mode connected`. Ce mode ne démarre et
n'arrête aucun service existant. Vérifier auparavant que les identifiants du
`run-id` sont libres ; le script les contrôle lui-même. Le scénario `full` en
mode raccordé n'interrompt pas le Core. Les proxys Vite ne servent qu'en
développement : un hébergement du build doit router les deux préfixes vers
les mêmes services.

## URLs et vérifications

- `http://127.0.0.1:5175/` : login de démonstration.
- `http://127.0.0.1:5175/operateur?station=SIMJURY0001-01` : Operator.
- `http://127.0.0.1:5175/superviseur` : Supervisor.
- `http://127.0.0.1:5175/cellule?station=SIMJURY0001-11` : Cellule.
- `http://127.0.0.1:5175/superviseur/poste/SIMJURY0001-01` : PosteDetail.
- `http://127.0.0.1:5175/api/v1/stations`, `/api/v1/kpi`,
  `/api/v1/alerts` : lecture Core via proxy.
- `http://127.0.0.1:5175/production/parts?limit=1` : lecture Edge via proxy.
- `http://127.0.0.1:18041/edge/sync/status` : état de l'outbox.

Les routes Operator et Supervisor utilisent les rôles de démonstration déjà
présents. Cellule est accessible sans session personnelle. Pour revenir au mode
graphique historique, omettre `VITE_LIVE_INDUSTRIAL` ou le mettre à `false`.

## Fichiers partagés et intégration Git

Les quatre pages de rôle gardent leurs composants d'origine. Le mode live leur
fournit des vues adaptées par `src/api/industrial-view.ts`, sans seconde page.
`LiveScreens.tsx` a été supprimé. `src/App.tsx` adapte
seulement le badge. `src/vite-env.d.ts` déclare le nouveau drapeau.
`vite.config.ts` ajoute le proxy Edge et conserve `/api`, donc les routes
MLOps existantes. `src/hooks/useApi.ts` efface l'erreur après une réponse
réussie, afin qu'une coupure temporaire ne laisse pas un message périmé.

Pour l'intégration ultérieure, reporter les deux commits locaux dans cet ordre :
`a598676` (SIM-01, copie locale du commit validé `6ffbd35`) puis le commit
`feat(industrial): connect HOVIS production screens to Core and Edge`
(INT-01). Si SIM-01 est déjà présent dans la cible, reporter seulement INT-01.
Revoir les conflits éventuels
sur ces quatre fichiers partagés : `App.tsx`, `vite.config.ts`,
`vite-env.d.ts`, `hooks/useApi.ts`. Aucun fichier AI Leader, MLOps, Core,
Production Engine, contrat commun ou modèle n'est modifié par INT-01.
Le correctif INT-01-FIX touche aussi `components/charts.tsx` pour rendre
explicitement un objectif horaire inconnu, sans changer les données mock.
