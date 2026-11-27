# Démo HOVIS : les commandes

Toutes les commandes se lancent dans PowerShell, **à la racine du dépôt** (`J:\Hackathon_Hutchinson`).
Détails : [README.md](README.md).

## Lancer la démo

| Je veux… | Commande |
|---|---|
| lancer la démo (1 poste actif, mode manuel) | `.\demo\start.ps1` |
| choisir le nombre de postes actifs (1 à 6), les autres « Pas d'activité » | `.\demo\start.ps1 -Stations 3` |
| le mode NOK automatique (la ligne ne s'arrête pas, l'opérateur n'est pas sollicité) | `.\demo\start.ps1 -Mode auto` |
| le mode NOK manuel (une pièce NOK attend CONFIRMER / LAISSER PASSER) — défaut | `.\demo\start.ps1 -Mode manuel` |
| **deux postes en mode auto** | `.\demo\start.ps1 -Stations 2 -Mode auto` |
| tous les serveurs **dans mon terminal** (pas de fenêtres ; Ctrl+C arrête tout) | `.\demo\start.ps1 -Stations 2 -Mode auto -Here` |
| choisir le **poste de travail** vérifié par chaque poste | `.\demo\start.ps1 -Stations 2 -Workstations press_cell:nok,electrical_bench` |
| des **vidéos** à la place de la webcam (une par poste ; petit bouton caméra sur l'écran opérateur, lecture unique) | `.\demo\start.ps1 -Stations 2 -Videos video1,video2` : vidéos rangées dans `data\raw\safety\videos`, ou un chemin vers le fichier |
| régler la **vitesse de lecture** des vidéos (0.1 à 4 ; 0.5 = deux fois plus lent) | `.\demo\start.ps1 -Stations 2 -Videos video3 -VideoSpeed 0.5` |
| sans l'analyse webcam EPI (sécurité) | `.\demo\start.ps1 -NoSafety` |
| sans le serveur AI leader (Databricks) | `.\demo\start.ps1 -NoAiLeader` |
| si PowerShell refuse le script | `powershell -ExecutionPolicy Bypass -File demo\start.ps1 -Stations 2 -Mode auto` |
| par le `.bat` (mêmes options) | `.\demo\start.bat -Stations 2 -Mode auto` |
| Git Bash / Linux : postes, mode, postes de travail | `./demo/start.sh 2 auto press_cell:nok,electrical_bench` |

Les options se combinent, par exemple :

```powershell
.\demo\start.ps1 -Stations 3 -Mode auto -Workstations press_cell,machine_cell_variant:nok -NoSafety -Here
```

Les ports déjà pris (8000 à 8006, 8040, 5173) sont libérés automatiquement au lancement.
Pour arrêter : fermer les fenêtres des serveurs, ou Ctrl+C avec `-Here`.

## Choisir le poste de travail (`-Workstations`)

Un nom par poste actif, dans l'ordre C3·P06, C3·P01, C3·P02, C3·P03, C3·P04, C3·P05, séparés par des virgules.

| Nom | Poste de travail |
|---|---|
| `machine_cell_variant` | Machine cell variant |
| `press_cell` | Press cell |
| `electrical_bench` | Electrical bench |
| `machine_cell` | Machine cell (vue de dessus) |

- `nom` (ou `nom:ok`) : photo conforme, poste **OK** tout de suite.
- `nom:nok` : objet dans le passage, poste **NOK**, NOK, puis OK.
- Les postes non cités gardent leur poste de travail par défaut (P06 et P01 : Machine cell variant NOK puis OK ; P02 : Press cell OK ; P03 : Electrical bench ; P04 : Machine cell ; P05 : Machine cell variant).

## Dans l'interface (http://localhost:5173)

| Je veux… | Action |
|---|---|
| me connecter en opérateur (poste C3·P06) | n'importe quel identifiant |
| me connecter en superviseur | `c.diaz@hutchinson.com` |
| lancer / relancer **le poste affiché** | clic sur le **logo ARGOS** (en haut à gauche, invisible) |
| passer à la vue superviseur (team leader) et revenir | **Ctrl+M** |
| passer à l'écran opérateur du poste suivant | **Ctrl+P** |
| ouvrir l'espace AI leader (cycle de vie des modèles) et revenir | **Ctrl+O** |
| signaler un problème (Modèle Quality, Modèle Workspace, Modèle EPI, Problème machine) | bouton **SIGNALER UN PROBLÈME** |
| jouer la vidéo du poste (démarré avec `-Videos`) | petit bouton **caméra « Lancer la vidéo »**, au-dessus de « Signaler un problème » |

Lancer tous les postes d'un coup, sans cliquer sur chaque logo :

```powershell
curl.exe -X POST http://localhost:8000/api/scenario/restart
```

## Databricks (espace AI leader)

Une seule fois par machine :

```powershell
winget install Databricks.DatabricksCLI          # puis fermer et rouvrir PowerShell
databricks auth login --host "https://dbc-11ee35c0-687b.cloud.databricks.com" --profile ARGOS
databricks current-user me --profile ARGOS       # vérification
```

Environnement Python du serveur AI leader (déjà fait sur ce PC) :

```powershell
python -m venv .venv-mlops
.venv-mlops\Scripts\python.exe -m pip install -r mlops\requirements-lock.txt
.venv-mlops\Scripts\python.exe -m pip install -e . --no-deps
```

## Vérifier le code

```powershell
pytest                     # tests
ruff check .               # lint
cd argos-ui; npx tsc --noEmit -p .; cd ..   # typage de l'interface
```
