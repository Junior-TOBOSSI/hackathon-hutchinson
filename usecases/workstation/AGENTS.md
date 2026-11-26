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
Chaîne « une photo contre la référence client » en place : alignement, emplacements d'éléments, zones sans objet ni personne (`model.py:ZoneWorkstationAnalyzer` v0.2.0), plus génération de variantes et évaluation sur les deux images disponibles (`stations/poste1.yaml`, `stations/poste2.yaml`). Détails et résultats dans [README.md](README.md). Le faux analyseur (`analyzer.py`) reste disponible.

## Décisions prises
<!-- Une ligne par décision : AAAA-MM-JJ HH:MM — décision — raison. -->
- 2026-11-26 — Deux couches : détection sur toute l'image (nomme l'objet) + différence avec la référence (attrape **n'importe quel** objet, même inconnu du modèle).
- 2026-11-26 — Zones et emplacements en polygones **normalisés**, un fichier par poste dans `stations/` : indépendants de la résolution, aucune image versionnée.
- 2026-11-26 — Objet « dans la zone » si **15 % de sa boîte** la recouvre (et non le centre de la boîte).
- 2026-11-26 — Différence en **couleur**, pas en niveaux de gris (une boîte orange sur un établi gris passait inaperçue) ; compensation globale de la luminosité.
- 2026-11-26 — Écarts écrits `"<label>@<zone>"` dans `misplaced`, objet inconnu `unknown_object` dans `detected` : **aucune modification du contrat**.
- 2026-11-26 — Inférence à blanc au chargement (première inférence YOLO sur CPU ≈ 2,6 s > limite du test de contrat) ; `sync=False` ; poids dans `data/models/workstation/`.
- 2026-11-26 — Précision client : **une photo** au début de la prise de poste, comparée à **la référence fournie par le client** ; persistance ramenée à 1 ; la main n'est pas un sujet.
- 2026-11-26 — **Alignement** SIFT + RANSAC avant toute comparaison (la référence ne vient pas de notre caméra) ; échec → `alignment_failed` en `a_verifier`, jamais un verdict deviné.
- 2026-11-26 — **Emplacements d'éléments** sur la référence : « pas à sa place » = l'emplacement a changé à plus de 25 %. Aucun modèle requis.
- 2026-11-26 — Zones d'intérêt : **ni objet ni personne** (`ignore_labels` vide par défaut).
- 2026-11-26 — Score d'un objet dans une zone = la plus forte des deux preuves (détecteur, taille du changement), au moins 0,45 (`a_verifier`) : un détecteur hésitant (personne à 0,38) masquait un changement net.
- 2026-11-26 — Jeu de test **généré** depuis les deux seules images disponibles (variantes avec vérité terrain), pas d'images aspirées du web ; les photos du mini poste serviront de jeu réel.

## Questions ouvertes
<!-- Questions sur le besoin métier ou les données, à poser à l'équipe ou à Hutchinson. -->
- « Ce qui n'est pas à sa place » : seulement les éléments listés (emplacements), ou **tout changement** sur le poste (objet inconnu posé hors zone) ? Aujourd'hui : seulement les emplacements et les zones.
- Zones `operator_spot` (l'opérateur **doit** y être, comme dans l'ancien système du client) : à prévoir ?
- Les zones et emplacements de `stations/` ont été placés à l'œil : à valider ou redessiner avec `draw_zones.py`.
- Contrat : un champ `foreign: list[str]` serait plus clair que `misplaced` pour les objets dans une zone interdite (modification de `contracts.py`, à décider en équipe).
- Racine du dépôt : extra `workstation` à passer à `ultralytics>=8.4` (YOLO26) ; ajouter `*.ts` au `.gitignore` (encodeur de texte YOLOE).

## Résultats
Variantes générées (seed 0, `--n 10`), CPU du PC de dev, seuils 0,4 / 0,7 :
- poste1 : 24/24 alertes levées pour la bonne raison, 0/20 fausse alerte (sans détecteur comme avec COCO).
- poste2 : 25/26, 0/20 ; le raté est un petit objet gris sur sol gris.
- Latence : ≈ 0,4 s sans détecteur, ≈ 0,8 s avec YOLO26n COCO (alignement SIFT compris).
- À refaire sur les photos réelles du mini poste (jeu mis de côté dans `data/test/workstation`).
