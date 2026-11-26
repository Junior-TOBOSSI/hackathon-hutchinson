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
Squelette en place : `model.py:ZoneWorkstationAnalyzer` (détection YOLO26 COCO + zones à garder vides par différence avec une image de référence). Détails dans [README.md](README.md). Le faux analyseur (`analyzer.py`) reste disponible.

## Décisions prises
<!-- Une ligne par décision : AAAA-MM-JJ HH:MM — décision — raison. -->
- 2026-11-26 — Caméra fixe vue de dessus ; deux besoins : identifier les éléments du poste, garder une zone d'intérêt vide.
- 2026-11-26 — Deux couches : détection sur toute l'image (nomme l'objet) + différence avec la référence dans la zone (attrape **n'importe quel** objet, même inconnu du modèle).
- 2026-11-26 — Zones en polygones **normalisés** dans `config.yaml`, dessinées avec `draw_zones.py` (local) : indépendantes de la résolution, aucune image envoyée en ligne.
- 2026-11-26 — Objet « dans la zone » si **15 % de sa boîte** la recouvre (et non le centre de la boîte) : un objet à cheval sur le bord est attrapé.
- 2026-11-26 — Différence en **couleur** (canal qui change le plus), pas en niveaux de gris : une boîte orange sur un établi gris a la même luminosité et passait inaperçue.
- 2026-11-26 — Compensation globale de la luminosité, pour qu'un changement d'éclairage ne soit pas une alerte.
- 2026-11-26 — Persistance de 3 images (1,5 s) dans l'analyseur, en attendant les épisodes côté back-end (correction n° 1).
- 2026-11-26 — Écarts de zone écrits `"<label>@<zone>"` dans `misplaced`, objet inconnu `unknown_object` dans `detected` : **aucune modification du contrat**.
- 2026-11-26 — Inférence à blanc au chargement : la première inférence YOLO sur CPU prend environ 2,6 s et dépassait la limite du test de contrat.
- 2026-11-26 — `sync=False` (Ultralytics) dans le détecteur ; poids et encodeur de texte YOLOE rangés dans `data/models/workstation/`.

## Questions ouvertes
<!-- Questions sur le besoin métier ou les données, à poser à l'équipe ou à Hutchinson. -->
- Faut-il **nommer** chaque élément du poste, et lesquels aurons-nous en démo ? Cela détermine les invites YOLOE et l'entraînement d'un YOLO26n sur nos éléments.
- Un élément du poste (outil) posé dans la zone est-il un écart ? (C'est le cas aujourd'hui.)
- Une **main immobile** dans la zone plus de 1,5 s est-elle un écart ? (C'est le cas aujourd'hui, voir le scénario `08_a_trancher`.) À coordonner avec le cas safety (main dans la presse).
- La zone doit-elle être vide en permanence, ou seulement à certains moments (lancement du cycle) ?
- Contrat : un champ `foreign: list[str]` serait plus clair que `misplaced` pour les objets dans une zone interdite. C'est une modification de `contracts.py`, à décider en équipe.
- Racine du dépôt : l'extra `workstation` du `pyproject.toml` impose `ultralytics>=8.2`, mais YOLO26 demande ≥ 8.4 (correction n° 6). Ajouter aussi `*.ts` au `.gitignore` (encodeur de texte YOLOE).

## Résultats
<!-- À remplir : jeu de test utilisé (data/test/workstation, nombre d'images), seuils retenus (low / high) et pourquoi,
     défauts détectés (rappel), fausses alertes (taux), latence moyenne sur CPU. -->
