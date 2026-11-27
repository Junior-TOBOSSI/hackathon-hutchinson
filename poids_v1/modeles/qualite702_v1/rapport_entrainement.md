# Rapport d'entraînement : qualité 702, version v1

Date : 2026-11-26 20:09  
Durée : 30 s  
Versions : Ultralytics 8.4.219, PyTorch 2.5.1+cu121, Python 3.10.10, Linux  
GPU : NVIDIA A100 80GB PCIe MIG 1g.10gb

## 1. Données

Dossier source : `/home/jovyan/hackathon/dataset_702_3cx_pli0`  
Test ajouté à l'entraînement : oui

| Bloc | Classe | Images |
|---|---|---|
| train | NOK_DOUBLE | 137 |
| train | NOK_SANS | 113 |
| train | OK | 368 |
| val | NOK_DOUBLE | 32 |
| val | NOK_SANS | 35 |
| val | OK | 103 |

Rafales (pièces) en entraînement : R00, R01, R02, R03, R04, R06, R07, R09, R10, R11, R13, R15, R16, R17, R18, R19, R20, R22, R23, R24, R25, R28  
Rafales (pièces) en val : R08, R12, R14, R21, R26, R27

Pourquoi val reste à part : il sert à choisir la meilleure époque et le seuil. Les vraies performances du modèle sont celles de la validation croisée, pas celles de val.

## 2. Hyperparamètres

| Paramètre | Valeur |
|---|---|
| modele_base | yolo26n-cls.pt |
| imgsz | 128 |
| epochs | 30 |
| patience | 10 |
| batch | 32 |
| seed | 0 |
| erasing | 0.0 |
| flipud | 0.5 |
| hsv_v | 0.6 |
| scale | 0.6 |
| rappel_vise | 0.9 |

## 3. Déroulé de l'entraînement

12 époques faites sur 30 ; meilleure précision val 1.000 à l'époque 2 (poids gardés = ceux de cette époque).

| Époque | Perte train | Perte val | Précision val |
|---|---|---|---|
| 1 | 0.915 | 0.702 | 0.635 |
| 2 | 0.364 | 0.031 | 1.000 |
| 3 | 0.188 | 2.117 | 0.794 |
| 4 | 0.254 | 0.190 | 0.912 |
| 5 | 0.123 | 0.054 | 0.994 |
| 6 | 0.157 | 0.001 | 1.000 |
| 7 | 0.084 | 0.114 | 0.959 |
| 8 | 0.102 | 0.095 | 0.959 |
| 9 | 0.084 | 0.019 | 1.000 |
| 10 | 0.056 | 0.017 | 1.000 |
| 11 | 0.065 | 0.017 | 1.000 |
| 12 | 0.045 | 0.013 | 1.000 |

## 4. Seuil de décision

Seuil NOK : **0.6365** (choisi sur val (règle de la validation croisée)).  
Sur val avec ce seuil : 67/67 photos NOK arrêtées (100 %), 0/103 photos OK rejetées (0 %).

Ces chiffres sont optimistes (val a servi à choisir l'époque et le seuil). Chiffres à annoncer : ceux de la validation croisée (synthese_c3f.md).

## 5. Fichiers produits

- `modele.pt` : poids
- `config_qualite702.yaml` : configuration d'inférence (à livrer avec les poids)
- `entrainement/` : sorties brutes d'Ultralytics (courbes, results.csv)

## 6. Alertes

- aucune
