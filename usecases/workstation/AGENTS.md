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
Faux analyseur (`analyzer.py:FakeWorkstationAnalyzer`) : résultats aléatoires mais plausibles, sans modèle.

## Décisions prises
<!-- Une ligne par décision : AAAA-MM-JJ HH:MM — décision — raison. -->

## Questions ouvertes
<!-- Questions sur le besoin métier ou les données, à poser à l'équipe ou à Hutchinson. -->

## Résultats
<!-- À remplir : jeu de test utilisé (data/test/workstation, nombre d'images), seuils retenus (low / high) et pourquoi,
     défauts détectés (rappel), fausses alertes (taux), latence moyenne sur CPU. -->
