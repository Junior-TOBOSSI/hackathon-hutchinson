# visionhub — vision industrielle multi-modèles

Hackathon **ESIGELEC × Hutchinson**, sujet « AI & Industrial Vision ».

Un système de vision au poste de production, organisé en plateforme commune. Trois cas d'usage s'y branchent :

| Cas d'usage | Question posée | Type de modèle visé |
|---|---|---|
| `quality` | La pièce est-elle conforme ? | détection d'anomalies (PatchCore, EfficientAD — Anomalib) |
| `workstation` | Le poste est-il configuré comme la référence ? | détection d'objets (YOLO — Ultralytics) |
| `safety` | Les EPI sont-ils portés ? Un téléphone est-il utilisé ? | détection d'objets (YOLO — Ultralytics) |

Pour l'instant, chaque cas d'usage tourne avec un **faux analyseur** : la chaîne complète fonctionne sans données, sans caméra et sans GPU. Chaque binôme le remplacera par son vrai modèle **sans toucher au reste du code**.

## Démarrage en moins de 5 minutes

### Avec Docker (recommandé)

```bash
git clone <url-du-depot> && cd <dossier>
docker compose up --build
```

- Tableau de bord : <http://localhost:8501>
- API et documentation interactive : <http://localhost:8000/docs>

Si le port 8000 ou 8501 est déjà pris, copiez `.env.example` vers `.env` et changez `API_PORT` ou `DASHBOARD_PORT`.

Commandes utiles :

| Action | Commande |
|---|---|
| Tests + lint | `docker compose run --rm tests` |
| Prendre en compte une modification de code | `docker compose restart api` (le code est monté dans le conteneur) |
| Repartir de zéro (efface les événements) | `docker compose down -v` |

### Sans Docker (Python 3.11+)

```bash
python -m venv .venv
# Windows : .venv\Scripts\activate     Linux/macOS : source .venv/bin/activate
pip install -e ".[dashboard,dev]"
python -m visionhub.demo        # API + tableau de bord ; Ctrl+C pour arrêter
pytest                          # tests, dont le test de contrat
ruff check . && ruff format .   # lint et formatage
```

## Ce que montre la démo

- Des images synthétiques passent dans les trois analyseurs, deux fois par seconde.
- Chaque résultat reçoit une décision : 🟢 `conforme`, 🟠 `a_verifier` ou 🔴 `anomalie`.
- Le tableau de bord affiche :
  - le flux des événements, filtrable par cas d'usage ;
  - les compteurs par cas d'usage et par décision ;
  - la file des cas « à vérifier », avec deux boutons (**Conforme** / **Défaut**) ;
  - un curseur à deux poignées par cas d'usage pour régler les seuils à chaud.

## Organisation du dépôt

```
visionhub/            socle commun : contrats, décision, registre, chaîne d'analyse, API
  contracts.py        ← les schémas de données (cœur du dépôt)
  production/         ARGOS Production Engine : cycles PLC, pièces, shifts, corrections, KPI
  argos_app.py        point d'entrée TEMPORAIRE : API historique + /production
  integration/        contrats ARGOS partagés : Edge→Core, Core, MLOps, PPE/Behavior, fixtures
frontend/             ARGOS Frontend (React) : espaces Opérateur, Superviseur, AI Leader
mlops/                ARGOS MLOps (DVC, MLflow) : périmètre et contrats
usecases/
  quality/            ← binôme qualité
  workstation/        ← binôme poste de travail
  safety/             ← binôme sécurité
    README.md         contrat d'entrée/sortie et marche à suivre pour brancher un vrai modèle
    AGENTS.md         journal du binôme (décisions, questions, résultats), lu par les assistants IA
    analyzer.py       faux analyseur
    config.yaml       classe chargée, seuils, paramètres
    notebooks/        expérimentations
    tests/
dashboard/app.py      tableau de bord Streamlit (aucune logique métier)
tests/                tests du socle, dont test_contract.py
data/                 données et poids, versionnés (Git LFS pour poids et vidéos, voir data/README.md)
docs/architecture.md  architecture en une page
docs/production-engine.md  ARGOS Production Engine (cycles, verdicts, KPI, endpoints)
docs/integration-contracts.md  contrats d'intégration des cinq groupes et catalogue des endpoints
docs/team-workstreams.md   répartition des groupes : branches, périmètres, livrables, tests
```

Les paramètres se règlent par variables d'environnement (`.env`), toutes documentées dans [.env.example](.env.example). Pour changer de source d'images, par exemple : `SOURCE=folder` et `SOURCE_PATH=data/test/quality`.

## Règles d'équipe

1. **Une branche par binôme** : `quality`, `workstation`, `safety`. On ne pousse jamais directement sur `main`.
2. **Pull request vers `main`**, relue par une autre personne de l'équipe. La CI (ruff + pytest) doit être verte.
3. **Le test de contrat est obligatoire** : `pytest tests/test_contract.py` doit passer **en local, avec votre vrai modèle**, avant d'ouvrir la PR. En CI, il est ignoré uniquement si les poids ou la bibliothèque du modèle manquent.
4. **Chaque binôme travaille dans son dossier** `usecases/<cas>/`. Toute modification de `visionhub/` (contrats, décision, registre, API) se discute d'abord avec l'équipe.
5. **Données et poids versionnés** dans `data/` depuis le 2026-11-27, avec l'accord de Hutchinson ; poids et vidéos via **Git LFS** (`git lfs install` une fois par machine). Toute nouvelle donnée client doit avoir le même accord avant d'être poussée. Aucune autre donnée n'est envoyée vers un service externe.
6. **Vie privée** : aucun visage stocké ni affiché, aucune identification de personne.
7. Tenir à jour le `README.md` et l'`AGENTS.md` de son cas d'usage.

## Assistants de code

`AGENTS.md` (racine et dossiers de cas d'usage), `CLAUDE.md` et `.github/copilot-instructions.md` donnent le contexte et les règles aux assistants (Claude Code, Cursor, Copilot…). Pour ChatGPT, collez le contenu d'`AGENTS.md` en début de conversation.

## Lancer les simulations (démo HOVIS)

Dans PowerShell, à la racine du dépôt. Toutes les options : [demo/COMMANDES.md](demo/COMMANDES.md) ; fonctionnement : [demo/README.md](demo/README.md).

```powershell
.\demo\start.ps1                                    # 1 poste actif (C3·P06), mode manuel
.\demo\start.ps1 -Stations 3                        # 3 postes actifs, les autres « Pas d'activité »
.\demo\start.ps1 -Stations 2 -Mode auto             # 2 postes, une pièce NOK n'arrête pas la ligne
.\demo\start.ps1 -Stations 2 -Mode manuel           # une pièce NOK attend CONFIRMER / LAISSER PASSER
.\demo\start.ps1 -Stations 2 -Mode auto -Here       # tous les serveurs dans ce terminal (Ctrl+C arrête tout)
.\demo\start.ps1 -Stations 2 -Workstations press_cell:nok,electrical_bench   # poste de travail de chaque poste
.\demo\start.ps1 -Stations 2 -Mode auto -Videos video3                       # vidéo à la place de la webcam (C3·P06)
.\demo\start.ps1 -Stations 2 -Mode auto -Videos video1,video2                # une vidéo par poste
.\demo\start.ps1 -Stations 2 -Mode auto -Videos ",video3"                    # vidéo sur C3·P01, webcam sur C3·P06
.\demo\start.ps1 -Stations 2 -Videos video3 -VideoSpeed 0.5                  # vidéo deux fois plus lente
.\demo\start.ps1 -NoSafety                          # sans l'analyse webcam EPI
.\demo\start.ps1 -NoAiLeader                        # sans le serveur AI leader (Databricks)
.\demo\start.bat -Stations 2 -Mode auto             # même chose par le .bat
powershell -ExecutionPolicy Bypass -File demo\start.ps1 -Stations 2 -Mode auto   # si PowerShell refuse le script
```

Git Bash / Linux : `./demo/start.sh 2 auto press_cell:nok,electrical_bench` (postes, mode, postes de travail) ; `VIDEO_SPEED=0.5` devant pour la vitesse des vidéos.

- Postes de travail (`-Workstations`) : `machine_cell_variant`, `press_cell`, `electrical_bench`, `machine_cell`, `cnc_cell` (même décor que les vidéos) ; `:nok` = démarre avec un objet dans le passage (NOK, NOK puis OK).
- Vidéos (`-Videos`) : un nom rangé dans `data/raw/safety/videos/` (`video1`, `video2`, `video3`) ou un chemin ; une par poste actif, dans l'ordre C3·P06, C3·P01…
- Dans l'interface (http://localhost:5173) : n'importe quel identifiant = opérateur ; **logo ARGOS** = lancer le poste affiché ; **Ctrl+M** = vue superviseur ; **Ctrl+P** = poste suivant ; **Ctrl+O** = espace AI leader ; bouton caméra **Lancer la vidéo** quand le poste a une vidéo.
- Lancer tous les postes d'un coup : `curl.exe -X POST http://localhost:8000/api/scenario/restart`.
