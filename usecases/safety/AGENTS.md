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
- 2026-11-26 — EPI suivis : casque, lunettes, gants, chaussures (pas de gilet) — besoin du binôme.
- 2026-11-26 — Données d'entraînement : SH17 (8 099 images, licence CC BY-NC-SA 4.0, usage non commercial, citer Ahmad & Rahimi 2024) — Hutchinson ne fournit pas de vidéos.
- 2026-11-26 — Ordre des classes SH17 = celui des poids officiels, pas celui du README — vérifié sur les annotations VOC.
- 2026-11-26 — Classes du modèle : person, face, helmet, glasses, gloves, shoes, head, hands, foot — person pour le contrat, face pour masquer les visages, head/hands/foot comme preuve d'absence d'un EPI.
- 2026-11-26 — Réentraînement depuis yolov8s COCO sur GPU (école), arrêt sur la validation SH17 — les poids SH17 officiels ratent 60 % des gants (rappel 0,40), même en baissant le seuil ; partir de COCO évite de réentraîner sur les mêmes images.
- 2026-11-26 — Visages toujours pixellisés avant affichage ou sauvegarde — RGPD.
- 2026-11-27 — **Modèle retenu : YOLO26s** (9 classes, `sh17_ours_yolo26s_640.pt`) — le plus précis des quatre modèles entraînés avec le même protocole (moyenne 0,704 ; gants 0,62, lunettes 0,68, chaussures 0,65, casque 0,68, validation SH17) ; YOLO26n pour un Raspberry Pi 5 sans accélérateur. Détails : `MODELS.md`.
- 2026-11-27 — (branche `integration`) Main gantée et retrait rapide des alertes : les correctifs provisoires d'`integration` (recouvrement 50 %, maintien 1,5 s) sont **remplacés par ceux d'EPI** (0169f6cd : main sur un gant à 30 % = main gantée ; 60ab2bda : alerte finie dès que l'EPI est vu porté sur 2 images, maintien de 5 s gardé si l'EPI est caché).

## Questions ouvertes
<!-- Questions sur le besoin métier ou les données, à poser à l'équipe ou à Hutchinson. -->
- Chaussures / gants / lunettes **de sécurité** ou n'importe lesquels ? SH17 ne fait pas la différence (à traiter plus tard).
- Ajouter `shoes` au contrat `PersonPPE` (`visionhub/contracts.py`) : accord de l'équipe nécessaire.

## Résultats
<!-- À remplir : jeu de test utilisé (data/test/safety, nombre d'images), seuils retenus (low / high) et pourquoi,
     défauts détectés (rappel), fausses alertes (taux), latence moyenne sur CPU. -->
