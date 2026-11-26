# AGENTS.md — cas d'usage `workstation`

> À lire avec le `AGENTS.md` de la racine, dont les règles s'appliquent ici. Le binôme tient ce fichier à jour pendant le hackathon.

## Objectif
Vérifier que le poste est configuré comme la référence : objets attendus présents et à leur place (détection d'objets YOLO, Ultralytics).

## Contrat
- **Entrée** : `analyze(image, meta)` ; image BGR `uint8 (H, W, 3)` déjà prétraitée ; `meta` de type `FrameMeta`.
- **Sortie** : `AnalysisResult(use_case="workstation", score ∈ [0, 1] (plus haut = pire), details=WorkstationDetails)`. Renvoyer le **score brut** : la décision est prise par la couche commune.
- Schéma : [visionhub/contracts.py](../../visionhub/contracts.py). Procédure de remplacement : [README.md](README.md).
- Exemple de `details` :
  ```json
  {"kind": "workstation", "expected": ["screwdriver", "gauge"], "detected": [{"label": "screwdriver", "confidence": 0.93, "bbox": {"x1": 0.02, "y1": 0.6, "x2": 0.22, "y2": 0.9}}], "missing": ["gauge"], "misplaced": []}
  ```

## État actuel
**Jeu de référence : `presse_5S_20`** (depuis le 2026-11-26 au soir). Les jeux précédents (`dataset_5S`, `poste1` / `poste2`) sont supprimés. Analyseur `model.py:ZoneWorkstationAnalyzer` v0.3.0 : alignement sur la meilleure vue (planche / pilote), normalité apprise sur les photos conformes et la référence, zones `zone_rouge` et `etabli`, emplacements des outils, YOLO26 pour nommer les personnes. Résultat : 15/15 anomalies, 0/4 fausse alerte (démonstration, pas un chiffre de performance). Détails dans [README.md](README.md).

## Décisions prises
<!-- Une ligne par décision : AAAA-MM-JJ HH:MM — décision — raison. -->
- 2026-11-26 — Une **photo** au début de la prise de poste, comparée à la référence ; persistance 1.
- 2026-11-26 — `presse_5S_20` fait foi ; le moteur générique est gardé, les données et fichiers de poste précédents sont supprimés.
- 2026-11-26 — **Deux vues** : « planche » (référence `good_002`, exclue de la mesure) couvre 19 photos sur 20 ; « pilote » (`reference.png`) ne couvre que `good_001`. La vue retenue est celle qui a le plus de correspondances (faux alignements : 47 à 80 ; bons : 97 et plus).
- 2026-11-26 — **Normalité apprise** (moyenne + dispersion par pixel) sur les photos conformes **et la référence elle-même** ; au moins 2 photos par vue, sinon comparaison à la référence seule.
- 2026-11-26 — L'arrière-plan de l'atelier (personnes, machines au loin) n'est jamais jugé : seules les zones et les emplacements comptent.
- 2026-11-26 — Le détecteur ne fait que **nommer** un changement ; YOLO26 COCO activé par défaut, car il nomme les personnes dans la zone rouge (sécurité) et la latence (0,8 s) est sans enjeu pour une photo par prise de poste.
- 2026-11-26 — Mesure en **validation croisée** : une photo conforme mise de côté à chaque fois (4 photos conformes seulement).
- 2026-11-26 — Différence en **couleur**, luminosité compensée ; alignement SIFT + RANSAC ; aucune modification du contrat (`"<label>@<zone>"` dans `misplaced`).

## Questions ouvertes
<!-- Questions sur le besoin métier ou les données, à poser à l'équipe ou à Hutchinson. -->
- **Lot pilote** : aucune photo conforme dans le cadrage « planche ». Ses anomalies sont détectées, mais avec des signalements en trop (pictogramme dans la zone rouge, bacs différents). Il faut des photos conformes de ce lot.
- Le pictogramme peint dans la zone rouge fait-il partie du poste normal, ou est-ce une variante de rendu ?
- Les étiquettes sont « indicatives » : à faire confirmer avant de citer les chiffres.
- En production : combien de photos conformes par caméra le client peut-il fournir pour apprendre la normalité ?
- Contrat : un champ `foreign: list[str]` serait plus clair que `misplaced` (modification de `contracts.py`, à décider en équipe).
- Racine du dépôt : extra `workstation` à passer à `ultralytics>=8.4` ; ajouter `*.ts` au `.gitignore`.

## Résultats
`presse_5S_20`, validation croisée (une photo conforme mise de côté à chaque fois), seuils 0,4 / 0,7, CPU :
- anomalies : 15/15 alertes pour la bonne raison (7 désordres, 4 objets et 4 personnes en zone rouge) ;
- photos conformes : 0/4 fausse alerte (`good_001` sur la vue pilote, `good_003` à `005` sur la planche) ;
- personnes nommées par YOLO26 : 2/4 (`anomaly_014` et `015`) ;
- alignement : 0 échec ; latence ≈ 0,4 s sans détecteur, ≈ 0,8 s avec.
- Ce n'est **pas** un chiffre de performance : 20 images, à présenter image par image.
