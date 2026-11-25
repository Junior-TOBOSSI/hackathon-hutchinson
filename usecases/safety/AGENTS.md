# AGENTS.md — cas d'usage `safety`

> À lire avec le `AGENTS.md` de la racine, dont les règles s'appliquent ici. Le binôme tient ce fichier à jour pendant le hackathon.

## Objectif
Détecter l'absence d'EPI (casque, gilet, lunettes, gants) et l'usage du téléphone (détection d'objets YOLO, Ultralytics). Aucune donnée d'identité, aucun visage.

## Contrat
- **Entrée** : `analyze(image, meta)` ; image BGR `uint8 (H, W, 3)` déjà prétraitée ; `meta` de type `FrameMeta`.
- **Sortie** : `AnalysisResult(use_case="safety", score ∈ [0, 1] (plus haut = pire), details=SafetyDetails)`. Renvoyer le **score brut** : la décision est prise par la couche commune.
- Schéma : [visionhub/contracts.py](../../visionhub/contracts.py). Procédure de remplacement : [README.md](README.md).
- Exemple de `details` :
  ```json
  {"kind": "safety", "person_count": 1, "persons": [{"person_index": 0, "bbox": null, "helmet": "absent", "vest": "present", "glasses": "uncertain", "gloves": "present", "phone": false}]}
  ```

## État actuel
Faux analyseur (`analyzer.py:FakeSafetyAnalyzer`) : résultats aléatoires mais plausibles, sans modèle.

## Décisions prises
<!-- Une ligne par décision : AAAA-MM-JJ HH:MM — décision — raison. -->

## Questions ouvertes
<!-- Questions sur le besoin métier ou les données, à poser à l'équipe ou à Hutchinson. -->

## Résultats
<!-- À remplir : jeu de test utilisé (data/test/safety, nombre d'images), seuils retenus (low / high) et pourquoi,
     défauts détectés (rappel), fausses alertes (taux), latence moyenne sur CPU. -->
