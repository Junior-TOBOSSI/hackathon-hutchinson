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
**Jeu de référence : `dataset_5S_80_496x325`** (depuis le 2026-11-26). Les essais précédents sur deux images isolées (poste1, poste2) ont été supprimés. Analyseur `model.py:ZoneWorkstationAnalyzer` v0.3.0 : alignement sur la meilleure vue, normalité apprise sur les photos conformes, zones `zone_interdite` et `plan_de_travail`, emplacements des outils. Mesure en validation croisée : 50/50 anomalies détectées, 1/29 fausse alerte. Détails dans [README.md](README.md).

## Décisions prises
<!-- Une ligne par décision : AAAA-MM-JJ HH:MM — décision — raison. -->
- 2026-11-26 — Une **photo** au début de la prise de poste, comparée à la référence ; persistance 1.
- 2026-11-26 — `dataset_5S_80_496x325` fait foi ; l'ancien travail (poste1/poste2, nettoyage de capture, variantes générées) est supprimé.
- 2026-11-26 — **Deux vues** (cadrages A et B) : une photo B ne s'aligne pas sur la référence A (19 correspondances, homographie fausse). La référence B est `good_017.png`, exclue de la mesure.
- 2026-11-26 — **Normalité apprise** (moyenne + dispersion par pixel) au lieu d'une image unique : avec une seule référence, 29/29 photos conformes étaient en fausse alerte (panneau, hachures, bacs qui varient d'une photo à l'autre).
- 2026-11-26 — Réglage `normal_k` = 4, `diff_threshold` = 25 : milieu de la plage stable (k = 3 à 4 donnent le même résultat), pour ne pas coller au petit jeu.
- 2026-11-26 — Mesure en **validation croisée en 5 groupes** sur les photos conformes.
- 2026-11-26 — Le détecteur ne fait que **nommer** un changement, il ne déclenche jamais d'alerte seul : COCO voyait l'établi comme un « refrigerator » et ajoutait 5 fausses alertes. Détecteur `none` par défaut sur ce poste.
- 2026-11-26 — Tout changement dans une zone vaut au moins 0,45 (`a_verifier`) : « aucun élément » veut dire aucun.
- 2026-11-26 — Différence en **couleur**, luminosité compensée ; alignement SIFT + RANSAC ; aucune modification du contrat (`"<label>@<zone>"` dans `misplaced`).

## Questions ouvertes
<!-- Questions sur le besoin métier ou les données, à poser à l'équipe ou à Hutchinson. -->
- `good_029` (bac bleu nettement décalé, étiqueté conforme) : est-ce un écart 5S pour le client ?
- Les étiquettes du jeu sont « indicatives, non validées » : à faire confirmer avant de citer les chiffres.
- En production : une référence **et quelques photos conformes** par caméra (pour apprendre la normalité). Combien le client peut-il en fournir ?
- Contrat : un champ `foreign: list[str]` serait plus clair que `misplaced` (modification de `contracts.py`, à décider en équipe).
- Racine du dépôt : extra `workstation` à passer à `ultralytics>=8.4` ; ajouter `*.ts` au `.gitignore`.

## Résultats
`dataset_5S_80_496x325`, validation croisée en 5 groupes, sans détecteur, seuils 0,4 / 0,7, CPU :
- anomalies : 50/50 alertes (38/38 désordres, 12/12 violations de zone), toutes pour la bonne raison ;
- photos conformes : 1/29 fausse alerte (`good_029`) ;
- alignement : 0 échec sur 79 photos (vue A : 32, vue B : 47) ;
- latence : ≈ 0,25 s par photo.
