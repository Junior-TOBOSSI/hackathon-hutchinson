# Modèles du cas Safety

> Fiche des modèles de détection des EPI et du téléphone. Les **fichiers de poids ne sont pas dans Git** (dépôt public) : ils sont dans le paquet privé construit par `notebooks/package_assets.py` (voir la fin de cette fiche).

## 1. Recommandation

| Usage | Modèle | Pourquoi |
|---|---|---|
| **Démo, et boîtier avec accélérateur IA** | **`sh17_ours_yolo26s_640.pt`** | le plus précis sur chacun des 4 EPI (moyenne 0,704) |
| Raspberry Pi 5 seul, si YOLO26s y est trop lent | `sh17_ours_yolo26n_640.pt` | 4 fois plus petit, précision proche de YOLOv8n |
| Téléphone (en plus du modèle EPI) | `yolov8n_coco.pt` | modèle COCO générique, classe `cell phone` |

Pour la production : réentraîner sur les images de l'usine (le levier de précision le plus fort), puis mesurer la vitesse sur le boîtier retenu.

## 2. Résultats (validation SH17, 810 images, mAP50 de 0 à 1)

| Modèle | Moyenne | Gants | Lunettes | Chaussures | Casque | Mains | Tête | Visage | Personne | Pied | Paramètres |
|---|---|---|---|---|---|---|---|---|---|---|---|
| YOLOv8n | 0,633 | 0,451 | 0,564 | 0,530 | 0,571 | 0,813 | 0,881 | 0,897 | 0,891 | 0,098 | 3,2 M |
| YOLO26n | 0,646 | 0,502 | 0,547 | 0,547 | 0,628 | 0,818 | 0,883 | 0,902 | 0,900 | 0,091 | 2,4 M |
| YOLOv8s | 0,680 | 0,531 | 0,653 | 0,583 | 0,609 | 0,848 | 0,892 | 0,913 | 0,898 | 0,196 | 11,1 M |
| **YOLO26s** | **0,704** | **0,620** | **0,675** | **0,648** | **0,679** | **0,861** | **0,908** | **0,915** | **0,908** | 0,127 | ≈ 9,5 M |

- Comparaison : les poids officiels des auteurs de SH17 (YOLOv8) détectent environ 0,30 sur les gants.
- Le casque (70 exemples en validation) et le pied (75) ont peu d'exemples : leurs chiffres sont incertains.
- **À compléter** : les mêmes mesures sur le **jeu de test** (810 images jamais utilisées), chiffres définitifs.
- Vitesse mesurée au processeur d'un ordinateur portable (Mac, 50 images de validation, temps médian, pendant que la démo tournait : valeurs absolues un peu hautes, comparaison juste) : YOLOv8n 57 ms, **YOLO26s 96 ms**, YOLOv8s 115 ms, modèle téléphone 58 ms. YOLO26s est donc plus précis **et** environ 17 % plus rapide que YOLOv8s. Démo complète (EPI + téléphone + floutage + vidéo) : 80 à 100 ms par image. À mesurer sur le boîtier.

## 3. Ce que les modèles détectent

9 classes, dans cet ordre : `person, face, helmet, glasses, gloves, shoes, head, hands, foot`.
`face` sert à flouter les visages ; `head`, `face`, `hands` et `foot` servent de **preuve** d'absence d'un EPI (un EPI n'est « absent » que si la partie du corps est visible sans lui). La logique est dans `yolo_analyzer.py`.

## 4. Entraînement (reproductible)

- Données : SH17 préparé par `notebooks/prepare_dataset.py --mode ours` (voir `DATASET.md`).
- Départ : poids COCO d'Ultralytics (`yolov8n.pt`, `yolov8s.pt`, `yolo26n.pt`, `yolo26s.pt`).
- Réglages : 640 px, 40 epochs au plus, arrêt anticipé après 10 epochs sans progrès, précision pleine (pas d'AMP), images en mémoire.
- GPU : NVIDIA A100 (tranche MIG 10 Go), Ultralytics 8.4.219, PyTorch 2.0.

```bash
D=data/processed/safety
python usecases/safety/notebooks/train_detector.py --epochs 40 --patience 10 --data $D/sh17_ours/data.yaml --weights data/models/yolo26s_coco.pt
python usecases/safety/notebooks/evaluate_model.py --weights data/models/safety/sh17_ours_yolo26s_640.pt --dataset $D/sh17_ours --split test --n 810
```

## 5. Empreintes (vérifier un fichier reçu : `shasum -a 256 <fichier>`)

| Fichier | SHA-256 |
|---|---|
| `safety/sh17_ours_yolov8s_640.pt` | `4928624ec4a0e0db210df4d0422550f791e1aff2699822b55c12a55beae33b8e` |
| `safety/sh17_ours_yolov8n_640.pt` | `4699f7439d39423cad3f27b60b570182acc4aa8fae5d185588961cfd7458e84e` |
| `yolov8n_coco.pt` | `f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36` |
| `safety/sh17_ours_yolo26s_640.pt`, `safety/sh17_ours_yolo26n_640.pt` | dans `SHA256SUMS` du paquet privé |

## 6. Récupérer les poids et le dataset (paquet privé)

Sur le serveur de l'école, depuis le dossier du projet (branche `safety-models`) :

```bash
python usecases/safety/notebooks/package_assets.py   # images redimensionnées à 1280 px
```

Le script crée `data/exports/safety_assets_<date>.tar.gz` (ignoré par Git), avec les modèles, le dataset préparé, un `README.txt` et `SHA256SUMS`. **À partager par un canal privé de l'équipe (Drive, Teams), jamais sur GitHub.** À l'arrivée :

```bash
tar -xzf safety_assets_<date>.tar.gz && cd safety_assets_<date> && shasum -a 256 -c SHA256SUMS
cp models/*.pt <projet>/data/models/safety/ && mv <projet>/data/models/safety/yolov8n_coco.pt <projet>/data/models/
```

Options : `--images none` (poids et annotations seulement, quelques dizaines de Mo), `--images full` (images d'origine, ≈ 13 Go).
