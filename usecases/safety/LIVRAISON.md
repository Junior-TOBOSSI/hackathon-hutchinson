# Livraison Safety pour l'intégration HOVIS

> Pour l'équipe d'intégration (RUN). Ce paquet contient tout ce qu'il faut pour brancher le vrai modèle Safety (EPI et téléphone) dans HOVIS. Le travail est sur la branche `EPI`, uniquement dans `usecases/safety/` : **ne pas fusionner la branche telle quelle** (elle part d'un ancien `main`), reprendre les fichiers listés ci-dessous.

## 1. Ce qui est livré

| Fichier | Rôle |
|---|---|
| `usecases/safety/yolo_analyzer.py` | Analyseur réel `YoloSafetyAnalyzer` (interface `Analyzer`, contrat `SafetyDetails` respecté) |
| `usecases/safety/hovis.py` | Traduction d'un résultat Safety en problèmes HOVIS (`StationIssue` d'argos-ui) |
| `usecases/safety/config.yaml` | Réglages (modèles, EPI obligatoires, seuils, lissage). Le faux analyseur reste par défaut |
| `usecases/safety/tests/test_yolo_logic.py` | 16 tests des règles métier, sans modèle |
| `usecases/safety/tests/test_hovis.py` | 9 tests de la traduction vers HOVIS |
| `usecases/safety/notebooks/` | Préparation des données, entraînement, évaluation, aperçu webcam (outils, hors plateforme) |
| `usecases/safety/AGENTS.md` | Décisions prises et questions ouvertes |

Les tests de contrat (`tests/test_contract.py`) passent avec le faux analyseur et avec le vrai.

## 2. Les modèles (hors Git)

Le dépôt est public : **les poids ne sont pas dans Git**. Ils sont transmis à part (clé USB ou dossier partagé). Vérifier l'empreinte après copie : `shasum -a 256 <fichier>`.

| Fichier, à placer dans `data/models/` | Rôle | SHA-256 |
|---|---|---|
| `safety/sh17_ours_yolov8s_640.pt` (22 Mo) | Modèle EPI recommandé : YOLOv8s, 9 classes | `4928624ec4a0e0db210df4d0422550f791e1aff2699822b55c12a55beae33b8e` |
| `safety/sh17_ours_yolov8n_640.pt` (6 Mo) | Modèle EPI de repli, plus léger : YOLOv8n | `4699f7439d39423cad3f27b60b570182acc4aa8fae5d185588961cfd7458e84e` |
| `yolov8n_coco.pt` (6 Mo) | Téléphones : modèle COCO générique, classe `cell phone` | `f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36` |

Classes du modèle EPI : `person, face, helmet, glasses, gloves, shoes, head, hands, foot`.

## 3. Activer l'analyseur

Dans `usecases/safety/config.yaml` :

```yaml
analyzer_class: usecases.safety.yolo_analyzer:YoloSafetyAnalyzer
params:
  weights: data/models/safety/sh17_ours_yolov8s_640.pt
```

Dépendance : `pip install -e ".[safety]"` (Ultralytics). Fonctionnement 100 % local : régler `YOLO_OFFLINE=1` et `yolo settings sync=False` (pas de télémétrie).

Mesures : ~80 ms par image sur un ordinateur portable (modèle EPI + téléphone).

## 4. Afficher les problèmes dans HOVIS

argos-ui attend, dans `StationLive.issues`, des objets `StationIssue` (`argos-ui/src/api/types.ts`). À l'endroit où `StationLive` est construit pour un poste :

```python
from usecases.safety.hovis import StationIssueTracker

tracker = StationIssueTracker(station_id="C3·P06")   # un par poste, gardé en mémoire
issues = tracker.update(safety_result)                # AnalysisResult du dernier passage
station_live["issues"] += issues
```

Exemple de sortie :

```json
{"id": "C3·P06:safety:gloves", "category": "SECURITE_EPI",
 "label": "Gants absents", "instruction": "Mettez vos gants", "since": "2026-11-27T08:00:00+00:00"}
```

| Résultat de l'analyseur | Problème HOVIS |
|---|---|
| casque `absent` | `SECURITE_EPI` · Casque absent · Mettez votre casque |
| lunettes `absent` | `SECURITE_EPI` · Lunettes absentes · Mettez vos lunettes |
| gants `absent` | `SECURITE_EPI` · Gants absents · Mettez vos gants |
| chaussures `absent` | `SECURITE_EPI` · Chaussures de sécurité non détectées · Vérifiez vos chaussures de sécurité |
| `phone = true` | `COMPORTEMENT` · Téléphone en main · Rangez votre téléphone |
| `uncertain` (partie du corps non visible) | aucun problème affiché |

Règles appliquées : rien n'est affiché si l'image est « conforme » (score lissé < 0,4) ; un seul problème par type pour le poste ; `since` garde l'heure de début tant que le problème dure ; aucune personne n'est identifiée.

## 5. Logique de décision (résumé)

- Un EPI est `absent` seulement si la partie du corps protégée est visible sans lui (main nue, tête, visage, corps entier sans chaussures). Sinon `uncertain`.
- Score : `0,4 + 0,6 × confiance de la preuve` ; chaussures déduites du corps entier : 0,5 (« à vérifier »).
- Lissage : le score retenu est le minimum des 3 dernières images (pas d'alerte sur une image isolée).
- Le gilet n'est pas vérifié (`vest = uncertain`).
- Les événements Safety sont continus (pas une pièce par cycle).

## 6. Demandes à l'intégration

1. **Contrat** : ajouter `shoes: PPEState = PPEState.UNCERTAIN` à `PersonPPE` (`visionhub/contracts.py`). Rétrocompatible. Tant que ce n'est pas fait, les chaussures comptent dans le score mais ne sont ni transmises au Core ni affichées.
2. **Téléphone** : la branche `detection-telephone` contient un autre modèle de téléphone. Décider lequel garder pour éviter deux détections concurrentes.
3. **Remontée au Core** : vérifier que les inférences Safety continues sont bien transmises (point ouvert du document de passation, section 16).

## 7. Résultats (validation SH17, 810 images)

| Modèle | mAP50 moyen | Gants | Lunettes | Chaussures | Casque |
|---|---|---|---|---|---|
| YOLOv8s (recommandé) | 0,68 | 0,53 | 0,65 | 0,58 | 0,61 |
| YOLOv8n (repli) | 0,63 | 0,45 | 0,56 | 0,53 | 0,57 |

Les chiffres définitifs (jeu de test de 810 images jamais utilisées) et la comparaison avec YOLO26 sont à venir.

Données : SH17 (licence CC BY-NC-SA 4.0, prototype uniquement). En production, réentraîner sur les images de l'usine.
