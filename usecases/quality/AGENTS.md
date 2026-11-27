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
Modèle réel branché (branche `integration`, 27/11) : `model702.py:Quality702Analyzer`, classification OK / NOK de la pièce 702 (modèle `qualite702 v1` de la branche `quality`, YOLO26n-cls, classes NOK_DOUBLE / NOK_SANS / OK). Score = somme des probabilités NOK ; seuils `low = high = 0,6365` (le `seuil_nok` du kit) : OK ou NOK, sans « à vérifier ». Le faux analyseur (`analyzer.py`) reste disponible.

Données (jamais versionnées) : poids `data/models/quality/qualite702_v1/modele.pt`, photos `data/raw/quality/702/{OK,NOK}/` (471 OK, 368 NOK).

## Décisions prises
- 2026-11-27 — Classification supervisée (kit `qualite702`) plutôt que détection d'anomalies : le jeu est étiqueté.
- 2026-11-27 — Même pré- et post-traitement que le kit (`qualite702/inference.py`) ; garde-fou sur l'ordre des classes au chargement.
- 2026-11-27 — Démo : uniquement les photos des rafales de validation (R08, R12, R14, R21, R26, R27), jamais vues à l'entraînement (le test a été fusionné à l'entraînement dans le kit). 103/103 OK et 67/67 NOK bien classés ; chiffre optimiste, car ces photos ont servi à choisir le seuil.
- 2026-11-27 — Écran : photo éclaircie (CLAHE + gamma) et agrandie pour l'opérateur ; le modèle voit la photo d'origine.
<!-- Une ligne par décision : AAAA-MM-JJ HH:MM — décision — raison. -->

## Questions ouvertes
<!-- Questions sur le besoin métier ou les données, à poser à l'équipe ou à Hutchinson. -->

## Résultats
<!-- À remplir : jeu de test utilisé (data/test/quality, nombre d'images), seuils retenus (low / high) et pourquoi,
     défauts détectés (rappel), fausses alertes (taux), latence moyenne sur CPU. -->
