# Démo HOVIS : prise de poste, puis qualité pièce par pièce, sur 1 à 6 postes

Serveurs de démonstration qui enchaînent les cas d'usage sur les écrans d'argos-ui (opérateur et team leader). Ils reprennent la démo Safety d'EPI (`usecases/safety/notebooks/hovis_demo.py`). Ce n'est **pas** l'API de la plateforme : seulement les routes dont les écrans ont besoin, pour le pitch.

## Architecture : un serveur par poste

```
argos-ui (5173) ──/api──> cellule C3 (8000) ──> poste C3·P06 (8001)  modèles workstation + qualité (+ webcam EPI)
                          demo/cell_server.py ──> poste C3·P01 (8002)  modèles workstation + qualité
                                              ──> ...                  (un serveur par poste actif)
```

- **Serveur d'un poste** (`demo/station_server.py`) : comme le PC d'un poste. Il charge ses modèles et les **sert par API** ; son scénario les appelle lui-même, si bien que sa fenêtre montre chaque appel :
  ```
  "POST /api/models/workstation/check?name=anomaly/anomaly_04.png" 200
  poste C3·P06 | workstation model <- anomaly/anomaly_04.png : KO ['Object in passage'] (495 ms)
  "POST /api/models/quality/classify?name=S6000702_1721747443890.jpg" 200
  poste C3·P06 | quality model <- S6000702_1721747443890.jpg : OK score_nok=0.0 (42 ms)
  ```
- **Serveur de la cellule** (`demo/cell_server.py`, port 8000) : aucun modèle. Il relaie les écrans et les boutons vers le serveur du poste concerné, construit la vue team leader (6 postes, alertes, « Prendre en charge ») et affiche « Pas d'activité » pour les postes sans serveur.

## Lancer

**Windows** : double-cliquer sur `demo\start.bat`, ou dans PowerShell à la racine du dépôt :

```powershell
.\demo\start.ps1                         # 1 poste actif (C3·P06)
.\demo\start.ps1 -Stations 3             # 3 postes actifs : C3·P06, C3·P01, C3·P02
.\demo\start.ps1 -Stations 6 -NoSafety   # 6 postes, sans la webcam EPI
.\demo\start.bat -Stations 3             # même chose par le .bat
```

Une fenêtre par poste actif, une pour la cellule, une pour l'interface, puis le navigateur sur http://localhost:5173 (modèles prêts en ~20 s). Fermer les fenêtres pour arrêter. Les ports déjà pris (8000 à 8006, 5173) sont libérés d'abord. Git Bash, Linux ou cluster : `./demo/start.sh 3` (ou `SAFETY=0 ./demo/start.sh 3`) ; tout tourne alors dans le même terminal.

Se connecter avec n'importe quel identifiant : opérateur du poste C3·P06. **Chaque poste attend qu'on le lance soi-même** : un clic sur le logo HOVIS (en haut à gauche, rien ne le signale) démarre la simulation **du poste affiché**, un autre clic la relance. Les autres postes restent « En attente de la prise de poste » jusqu'à ce qu'on ouvre leur écran (Ctrl+P) et qu'on clique sur leur logo. Tout lancer d'un coup : `curl -X POST http://localhost:8000/api/scenario/restart` (sans `?station=`).

## Les postes

Activés dans cet ordre (`-Stations N` = les N premiers) ; les autres affichent « Pas d'activité » (statut gris côté team leader) :

| Rang | Poste | Poste de travail vérifié | Prise de poste |
|---|---|---|---|
| 1 | C3·P06 | Machine cell variant | `anomaly_04` KO, `anomaly_04` KO, `good_04` OK — + webcam EPI |
| 2 | C3·P01 | Machine cell variant | KO, KO, OK (même séquence) |
| 3 | C3·P02 | **Press cell** (autre poste, autres images) | `good_01` : **OK d'emblée** |
| 4 | C3·P03 | Electrical bench | `good_01` : OK d'emblée |
| 5 | C3·P04 | Machine cell (vue de dessus) | `good_01` : OK d'emblée |
| 6 | C3·P05 | Machine cell variant | `good_03` : OK d'emblée |

Dès 3 postes actifs, au moins un a donc un poste de travail différent et démarre sans problème. Chaque poste voit d'autres photos.

**Pièces KO, tous postes confondus** : avant chaque pièce, le poste demande à la cellule (`POST /api/cell/next-part`) si c'est une bonne pièce ou une KO. La cellule numérote les pièces de tous ses postes : **au plus 2 KO sur 200 pièces consécutives de la cellule**, quel que soit le nombre de postes. Le premier KO arrive tôt, sur la **4e pièce** du premier poste qui y arrive (après ses 3 premières pièces), pour que la démo en montre un ; ensuite un KO toutes les 100 pièces de la cellule. Le modèle classe correctement toutes les photos de validation (0 erreur sur 103 OK / 67 NOK) : une photo de bonne pièce donne OK, une photo NOK donne KO.

## Le scénario d'un poste

| Étape | Ce que montre l'écran | Cas d'usage |
|---|---|---|
| 0. En attente | « En attente de la prise de poste », jusqu'au clic sur le logo | — |
| 1. Prise de poste | photo du poste à la place de la pièce, **OK** ou **KO** (bandeau « Dégagez le passage », tuile Poste rouge) ; une photo toutes les 2,5 s jusqu'à un OK | workstation |
| 2. Poste validé | « Poste validé : l'activité commence » ; la vérification n'est faite **qu'une fois** | workstation |
| 3. Activité | une pièce toutes les 3 s ; KO décidés par la cellule (4e pièce, puis 2 au plus sur 200 pièces, tous postes) | quality (`qualite702 v1`) |
| 4. Pièce KO | le défilement **s'arrête** : **CONFIRMER** (pièce au rebut) ou **LAISSER PASSER** (erreur modèle : la pièce compte comme bonne, le team leader reçoit une alerte à valider) | quality |

## Ce qui est réel et ce qui ne l'est pas

- **Réel** : les verdicts du poste (analyseur workstation ; les photos jugées ne servent pas à apprendre la normalité) et les verdicts qualité (modèle de la branche `quality`, sur les seules photos des **rafales de validation** R08, R12, R14, R21, R26, R27, jamais vues à l'entraînement).
- **Affichage** : les photos qualité (126 × 86, très sombres) sont éclaircies et agrandies pour l'écran ; le modèle analyse la photo d'origine.
- **Compteurs** : la production du shift jusqu'au démarrage (simulée par le code d'EPI), plus les pièces de la démo. Le plan n'avance **que pendant que la ligne produit**. Le shift (A 5-13 h, B 13-21 h, C 21-5 h) suit l'heure.
- **Sécurité (EPI)** : l'analyse webcam d'EPI tourne dans le serveur de C3·P06 si ses poids sont présents (`data/models/safety/sh17_ours_yolov8s_640.pt`, `data/models/yolov8n_coco.pt`) et qu'une webcam est branchée. Sans EPI, la tuile Sécurité passe au rouge et l'image caméra (visage flouté) remplace la pièce. `-NoSafety` / `SAFETY=0` la coupe.

## Vues et raccourcis

- **Ctrl+M** : écran opérateur ↔ vue team leader. Aucun signe à l'écran.
- **Ctrl+P** : écran opérateur du poste suivant (C3·P01 → … → P06). Remplace l'impression du navigateur.
- Ou se connecter avec `c.diaz@hutchinson.com` (ou un identifiant contenant « leader », « manager » ou « chef »).

## Réglages (variables d'environnement d'un serveur de poste)

| Variable | Défaut | Rôle |
|---|---|---|
| `STATION_ID` · `PROFILE` · `PORT` | `C3·P06` · 0 · 8001 | poste, rang (tableau ci-dessus), port — fixés par les scripts |
| `CHECK_PERIOD` | 2.5 | secondes par photo du poste |
| `QUALITY_PERIOD` | 3 | secondes par pièce |
| `VALIDATED_HOLD` | 3 | secondes d'affichage de « Poste validé » |
| `CELL_URL` | `http://127.0.0.1:8000` | serveur de cellule qui décide des KO (sans lui : même règle, pour le poste seul) |
| `SAFETY` | 0 | 1 = analyse webcam EPI (le script la met sur C3·P06) |

Serveur de cellule : `ACTIVE_STATIONS` (1 à 6), `FIRST_STATION_PORT` (8001), `KO_MAX` (2) KO au plus sur `KO_WINDOW` (200) pièces, `FIRST_KO_AT` (4) : la pièce du premier KO.

## Données attendues (jamais versionnées)

```
data/raw/workstation/poste_*_5s_11/               # jeux des 4 postes de travail
data/raw/quality/702/{OK,NOK}/                    # photos qualité (Dataset.zip)
data/models/quality/qualite702_v1/modele.pt       # poids du modèle qualité (+ config_qualite702.yaml)
data/models/workstation/yolo26n.pt                # détecteur de personnes
```

## Routes

| Serveur | Route | Rôle |
|---|---|---|
| poste | `POST /api/models/workstation/check` | modèle workstation (corps : la photo) → verdict, écarts, latence |
| poste | `POST /api/models/quality/classify` | modèle qualité (corps : la photo) → verdict, `score_nok`, défaut, probabilités |
| poste | `GET /api/station/summary` · `/api/station/alerts` | carte et alertes du poste, lues par la cellule |
| les deux | `GET /api/stations/{id}/live` | écran du poste (`StationLive`, avec `startup` et `part.awaitingConfirmation`) |
| les deux | `POST /api/stations/{id}/parts/confirm` · `/release` | CONFIRMER · LAISSER PASSER |
| les deux | `POST /api/scenario/restart?station={id}` | démarrer / relancer ce poste (sans `station` : tous) |
| cellule | `POST /api/cell/next-part?station={id}` | bonne pièce ou KO ? (budget de KO de la cellule) |
| cellule | `GET /api/cells/C3/overview` · `/alerts` | vue team leader |
| cellule | `GET /api/scenario/status` | postes actifs et leurs ports (débogage) |
