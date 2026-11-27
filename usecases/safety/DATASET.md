# Dataset du cas Safety

> Comment refaire **exactement** le dataset d'entraînement. Les images et les annotations ne sont pas dans Git (dépôt public, photos de personnes) : on les retélécharge à la source, ou on les reçoit dans le paquet privé (voir `MODELS.md`, section 6).

## 1. Source

- **SH17** (Safety Helmet 17 classes), Ahmad et Rahimi, 2024 : 8 099 photos industrielles issues de Pexels, annotées en 17 classes.
- Licence **CC BY-NC-SA 4.0** : usage non commercial, citer les auteurs, partager à l'identique. Convient au prototype ; en production, réentraîner sur les images de l'usine.
- Téléchargement : Kaggle (jeu « SH17 dataset for PPE detection »), dans `data/raw/safety/sh17/` (`images/`, `labels/`, `voc_labels/`).

## 2. Préparation

```bash
python usecases/safety/notebooks/explore_sh17.py          # contrôle : images, annotations, classes
python usecases/safety/notebooks/prepare_dataset.py --mode ours
```

- Sortie : `data/processed/safety/sh17_ours/` (`data.yaml`, `train.txt`, `val.txt`, `test.txt`, `labels/`, `images/` en liens vers les originaux).
- **9 classes gardées**, dans cet ordre : `person, face, helmet, glasses, gloves, shoes, head, hands, foot`.
- L'ordre des 17 classes d'origine est celui des poids officiels de SH17, pas celui de leur README (vérifié sur les annotations VOC).
- Autres modes : `--mode all` (17 classes, pour comparaison), `--mode hand`.

## 3. Découpage (fixe)

| Partie | Images | Usage | Empreinte de la liste triée (16 premiers caractères du SHA-256) |
|---|---|---|---|
| train | 6 479 | entraînement | `827ad5c4c1ce50bc` |
| val | 810 | choix de l'epoch, comparaison des modèles | `545e319ee15b7425` |
| test | 810 | chiffres définitifs, jamais utilisé avant | `0eb781604de99e24` |

Graine du découpage : `SPLIT_SEED = 0` dans `prepare_dataset.py`. **Ne jamais la changer** : le jeu de test changerait, et les résultats ne seraient plus comparables.

Vérifier qu'on a bien le même découpage :

```bash
for f in train val test; do printf "%s " $f; sort data/processed/safety/sh17_ours/$f.txt | shasum -a 256 | cut -c1-16; done
```

Les listes contiennent des chemins relatifs (`./images/…`) : les empreintes sont les mêmes quel que soit le dossier du projet.
