# Démo HOVIS : prise de poste, puis qualité pièce par pièce

Serveur de démonstration qui enchaîne les cas d'usage sur **l'écran opérateur** d'argos-ui. Il reprend le principe de la démo Safety d'EPI (`usecases/safety/notebooks/hovis_demo.py`). Ce n'est **pas** l'API de la plateforme : il n'expose que les routes dont l'écran opérateur a besoin, pour le pitch.

## Lancer

```bash
# 1. le serveur du scénario (racine du dépôt, environnement Python activé)
python -m uvicorn demo.scenario:app --port 8000

# 2. l'interface, en mode live (redirige /api vers le port 8000)
cd argos-ui
npm install                         # la première fois
VITE_USE_MOCK=false npm run dev     # PowerShell : $env:VITE_USE_MOCK="false"; npm run dev
```

Ouvrir http://localhost:5173. Se connecter avec n'importe quel identifiant : le serveur renvoie l'opérateur du poste C3·P06.

**Le scénario attend un clic sur le logo HOVIS** (en haut à gauche de l'écran opérateur ; rien ne le signale). Un clic démarre la simulation, un autre la relance depuis le début (équivalent : `curl -X POST http://localhost:8000/api/scenario/restart`).

## Le scénario

| Étape | Ce que montre l'écran | Cas d'usage |
|---|---|---|
| 0. En attente | « En attente de la prise de poste », jusqu'au clic sur le logo | — |
| 1. Prise de poste, photo 1/3 | photo du poste à la place de la pièce : bac dans le passage → **KO**, bandeau « Dégagez le passage », tuile Poste rouge | workstation (`machine_cell_variant`, `anomaly_04`) |
| 2. Photo 2/3 | la même photo → toujours **KO** | workstation (`anomaly_04`) |
| 3. Photo 3/3 | photo conforme → **OK**, puis « Poste validé : l'activité commence » | workstation (`good_04`) |
| 4. Activité | une pièce toutes les 2 s, **un défaut toutes les 10 pièces** (pièces 10, 20, 30…) | quality (`qualite702 v1`) |
| 5. Pièce KO | le défilement **s'arrête** : **CONFIRMER** (pièce au rebut) ou **LAISSER PASSER** (erreur modèle : la pièce compte comme bonne, l'erreur est comptée) | quality |

La vérification du poste n'est faite **qu'une fois** : une fois le poste validé, on ne la refait plus.

## Ce qui est réel et ce qui ne l'est pas

- **Réel** :
  - les verdicts du poste, donnés par l'analyseur workstation ; `good_04` n'est pas utilisé pour apprendre la normalité, il est jugé ;
  - les verdicts qualité, donnés par le modèle de la branche `quality`, sur les seules photos des **rafales de validation** (R08, R12, R14, R21, R26, R27 : 103 OK, 67 NOK). Le modèle n'a pas appris sur ces photos ; elles ont servi à choisir son seuil.
- **Affichage** : les photos qualité (126 × 86, très sombres) sont éclaircies et agrandies pour l'écran. Le modèle analyse toujours la photo d'origine.
- **Compteurs** : la production du shift en cours jusqu'au démarrage (simulée par le code d'EPI, environ 96 % du plan à 125 pièces/h), plus les pièces de la démo. Le plan n'avance au rythme de la démo **que pendant que la ligne produit** : une pièce KO en attente de l'opérateur ne creuse pas le retard. Le shift (A 5-13 h, B 13-21 h, C 21-5 h) suit l'heure.
- **Sécurité (EPI)** : l'analyse webcam d'EPI tourne si ses poids sont présents (`data/models/safety/sh17_ours_yolov8s_640.pt`, plus `data/models/yolov8n_coco.pt` pour les téléphones) et qu'une webcam est branchée. Elle voit la personne devant le PC : sans EPI, la tuile Sécurité passe au rouge et l'image caméra remplace la pièce (règle d'EPI : la sécurité d'abord). `SAFETY=0` la coupe.

## Vue superviseur (team leader)

- **Ctrl+M** : passe de l'écran opérateur à la vue team leader, et retour. Aucun signe à l'écran.
- Ou se connecter avec `c.diaz@hutchinson.com` (ou un identifiant contenant « leader », « manager » ou « chef »).
- Cellule 3 : **6 postes** (C3·P01 à C3·P06). C3·P06 est le poste du scénario : vrais verdicts, vraies alertes (prise de poste non conforme, pièce KO en attente, pièce laissée passer à confirmer). Les 5 autres sont simulés par le code d'EPI. Les écrans viennent du patch d'EPI (`usecases/safety/integration/argos-ui-operateur.patch`) : cartes de postes, « Prendre en charge ».

## Réglages (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `CHECK_PERIOD` | 2.5 | secondes par photo du poste |
| `QUALITY_PERIOD` | 2 | secondes par pièce |
| `VALIDATED_HOLD` | 3 | secondes d'affichage de « Poste validé » avant l'activité |
| `WORKSTATION_SECTION` | `machine_cell_variant` | section du poste vérifié |
| `QUALITY_PATTERN` | `9:1` | blocs « OK:KO » répétés : 9 bonnes puis 1 KO |
| `SAFETY` | 1 | 0 = pas d'analyse webcam |

## Données attendues (jamais versionnées)

```
data/raw/workstation/poste_variante_5s_11/        # jeu de la section (poste)
data/raw/quality/702/{OK,NOK}/                    # photos qualité (Dataset.zip)
data/models/quality/qualite702_v1/modele.pt       # poids du modèle qualité (+ config_qualite702.yaml)
data/models/workstation/yolo26n.pt                # détecteur de personnes (téléchargé une fois)
```

## Routes

| Route | Rôle |
|---|---|
| `GET /api/stations/{id}/live` | état complet du poste (`StationLive`), avec `startup` (prise de poste) et `part.awaitingConfirmation` |
| `POST /api/stations/{id}/parts/confirm` | l'opérateur confirme la pièce KO |
| `POST /api/stations/{id}/parts/release` | l'opérateur laisse passer la pièce KO (erreur modèle) |
| `GET /api/scenario/workstation.jpg` · `/part.jpg` | images affichées (poste annoté, pièce) |
| `POST /api/scenario/restart` | démarrer ou relancer la simulation (clic sur le logo) |
| `GET /api/scenario/status` | état interne (débogage) |
