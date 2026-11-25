# AGENTS.md — cas d'usage `quality`

> À lire avec le `AGENTS.md` de la racine, dont les règles s'appliquent ici. Le binôme tient ce fichier à jour pendant le hackathon.

## Objectif
Détecter les pièces non conformes (rayures, manques, taches…) par détection d'anomalies (PatchCore / EfficientAD, Anomalib).

## Contrat
- **Entrée** : `analyze(image, meta)` ; image BGR `uint8 (H, W, 3)` déjà prétraitée ; `meta` de type `FrameMeta`.
- **Sortie** : `AnalysisResult(use_case="quality", score ∈ [0, 1] (plus haut = pire), details=QualityDetails)`. Renvoyer le **score brut** : la décision est prise par la couche commune.
- Schéma : [visionhub/contracts.py](../../visionhub/contracts.py). Procédure de remplacement : [README.md](README.md).
- Exemple de `details` :
  ```json
  {"kind": "quality", "zones": [{"bbox": {"x1": 0.22, "y1": 0.77, "x2": 0.35, "y2": 0.91}, "score": 0.46}], "heatmap_ref": null}
  ```

## État actuel
Faux analyseur (`analyzer.py:FakeQualityAnalyzer`) : résultats aléatoires mais plausibles, sans modèle.

## Décisions prises
<!-- Une ligne par décision : AAAA-MM-JJ HH:MM — décision — raison. -->

## Questions ouvertes
<!-- Questions sur le besoin métier ou les données, à poser à l'équipe ou à Hutchinson. -->

## Résultats
<!-- À remplir : jeu de test utilisé (data/test/quality, nombre d'images), seuils retenus (low / high) et pourquoi,
     défauts détectés (rappel), fausses alertes (taux), latence moyenne sur CPU. -->
