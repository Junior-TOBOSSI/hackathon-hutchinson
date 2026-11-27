# Module qualité 702 : guide d'intégration

Contrôle qualité de la référence 702 (Hutchinson) : une photo de la gorge de la pièce, une réponse.
Règle client : **OK = exactement 1 joint** dans la gorge ; **NOK = aucun joint ou plus d'un joint**.

## Ce que contient le kit (correspondance avec la liste d'intégration)

| Élément demandé | Fichier | Remarque |
|---|---|---|
| train.py | `train.py` + `hyperparametres.yaml` | entraîne une version et écrit poids + config + rapport |
| Code d'inférence | `qualite702/inference.py` (classe `Qualite702`) | `predire(image)` renvoie un dictionnaire JSON |
| Poids entraînés | `modeles/qualite702_v1/modele.pt` | version v1 |
| requirements.txt | `requirements.txt` | PyTorch à installer à part (voir plus bas) |
| Configuration du modèle | `modeles/qualite702_v1/config_qualite702.yaml` | classes, seuil, taille d'image, hyperparamètres, versions |
| Prétraitement | fait par Ultralytics dans `Qualite702` | détail ci-dessous |
| Post-traitement | `Qualite702.interpreter()` | détail ci-dessous |
| Classes et labels | `config_qualite702.yaml` (classes) + `LIBELLES` | OK, NOK_SANS, NOK_DOUBLE |
| Format du dataset | `donnees/preparer_3classes.py` | détail ci-dessous |
| Code d'évaluation | `evaluer.py` | même code que la production, compare deux versions |
| Métriques initiales | `metriques/` (synthèses de la validation croisée) | chiffres ci-dessous |
| Export ONNX | `export_onnx.py` → `modele.onnx` + `config_qualite702_onnx.yaml` | vérifie l'égalité .pt / .onnx |

## Utilisation

```python
from qualite702 import Qualite702

q = Qualite702("modeles/qualite702_v1/config_qualite702.yaml")   # charger une fois au démarrage
resultat = q.predire(image)   # chemin, image OpenCV (BGR, numpy) ou image PIL
if resultat["verdict"] == "NOK":
    ...   # pièce vers le bac rebuts, afficher resultat["libelle"]
```

Exemple de sortie : `exemple_sortie.json`. Champs principaux :

| Champ | Valeurs | Sens |
|---|---|---|
| `verdict` | `OK`, `NOK`, `A_VERIFIER` | `A_VERIFIER` n'existe que si `seuil_a_verifier` est renseigné dans la config (désactivé en v1) |
| `type_defaut` | `null`, `NOK_SANS`, `NOK_DOUBLE` | type le plus probable quand la pièce est rejetée |
| `libelle` | texte | phrase prête à afficher sur l'écran opérateur |
| `score_nok` | 0 à 1 | somme des probabilités des classes NOK |
| `modele.version` | ex. `v1` | à stocker avec chaque événement (traçabilité, comparaison des versions) |
| `latence_ms` | nombre | temps de calcul de la photo |

Correspondance possible avec les décisions de la plateforme : `OK` → conforme, `A_VERIFIER` → a_verifier, `NOK` → anomalie.

Test en ligne de commande :

```bash
python predire.py --config modeles/qualite702_v1/config_qualite702.yaml photo.jpg
```

## Prétraitement

Passer l'image brute de la caméra : ne rien redimensionner soi-même.
Ultralytics (fonction `classify_transforms`) redimensionne le petit côté à 128 px, garde le carré central 128 x 128, passe en RGB et divise les valeurs par 255.
Conséquence pour le cadrage : les photos font 126 x 86 px ; une bande d'environ 20 px de chaque côté (en pixels d'origine) n'est pas vue par le modèle. La gorge doit rester dans la partie centrale.
Si un jour on remplace Ultralytics par onnxruntime seul, il faudra reproduire exactement ces étapes ; `export_onnx.py` sert à vérifier qu'on obtient les mêmes probabilités.

## Post-traitement

```
score_nok = P(NOK_SANS) + P(NOK_DOUBLE)
score_nok >= seuil_nok                         -> NOK
seuil_a_verifier <= score_nok < seuil_nok      -> A_VERIFIER (si activé)
sinon                                          -> OK
```

On additionne les deux classes NOK : une photo à 40 % DOUBLE, 25 % SANS, 35 % OK est rejetée, même si OK est la classe la plus probable.
Le seuil est choisi sur des pièces jamais vues à l'entraînement (bloc val), avec la règle : arrêter au moins 90 % des NOK, puis rejeter le moins de OK possible.

## Format du dataset (réentraînement)

```
dataset_702_3c_pliN/
  train/OK/*.jpg   train/NOK_SANS/*.jpg   train/NOK_DOUBLE/*.jpg
  val/...          test/...
  repartition.csv  (fichier, classe, type, rafale, pli, split)
```

Construit par `donnees/preparer_3classes.py` à partir des photos brutes (`702/OK`, `702/NOK`) et du tri des rafales NOK (`tri_nok.csv`).
Point important : les photos sont découpées **par rafale** (une rafale = une pièce photographiée plusieurs fois). Les photos d'une même pièce ne sont jamais à la fois en entraînement et en test, sinon les scores seraient gonflés.

Entraîner une nouvelle version :

```bash
python train.py --dataset <dossier préparé> --fusionner-test --sortie modeles/qualite702_v2 --version v2 --device 0
python evaluer.py --config modeles/qualite702_v2/config_qualite702.yaml --images <dossier préparé>/val \
    --sortie modeles/qualite702_v2/eval_val --comparer modeles/qualite702_v1/eval_val/metriques.json
```

## Métriques initiales (validation croisée 5 plis, par pièce)

Chaque pièce a servi une fois de test sans avoir été vue à l'entraînement. Détail dans `metriques/`.

Règle de données : les photos où la pièce est mal positionnée devant la caméra sont exclues (anneau de la gorge à plat en bas de l'image, repère rejeté dans le coin haut droit, au lieu de l'arc sur le côté droit visible sur toutes les autres pièces). La règle a été vérifiée sur les 29 pièces : une seule est concernée, R05 (pièce NOK sans joint, 51 photos). Exclusion à faire confirmer par Hutchinson.

| Mesure | Avec R05 (série c3f) | Sans R05 (série c3fx) |
|---|---|---|
| Photos NOK arrêtées (rappel) | 86 % (318 / 368) | voir `metriques/synthese_c3fx.md` |
| Photos OK rejetées à tort | 1 % | idem |
| Pièces NOK détectées | 14 / 15 | idem |
| Pièces OK rejetées | 0 / 14 | idem |
| Confusion SANS / DOUBLE | 0 | idem |

Conséquence pour la production : le modèle suppose une pièce positionnée comme sur les photos d'entraînement. Le positionnement doit être garanti par le poste (caméra fixe, pièce en butée ou dans un gabarit).
Chiffres mesurés sur 28 à 29 pièces : ce sont des ordres de grandeur.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate        # Windows : .venv\Scripts\activate
# PyTorch d'abord, selon la machine :
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # PC sans GPU NVIDIA
pip install -r requirements.txt
```

Les versions exactes utilisées pour l'entraînement sont dans `config_qualite702.yaml` (rubrique `versions`).

## Licence

Ultralytics (YOLO) est sous licence AGPL-3.0 : un logiciel qui l'intègre et qui est distribué ou exposé en réseau doit publier son code sous la même licence, ou prendre une licence Enterprise. À signaler à Hutchinson avant tout usage hors hackathon.
