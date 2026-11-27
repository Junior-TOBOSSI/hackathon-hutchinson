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
**Quatre sections** (27/11) : un poste par jeu `poste_*_5s_11`, un fichier de poste annoté en anglais par section dans `stations/`. Les jeux précédents sont supprimés. Analyseur `model.py:ZoneWorkstationAnalyzer` : alignement, normalité apprise, zones à garder libres, éléments à leur place, personnes autorisées par zone ou partout. Démo Streamlit avec choix de la section et de la photo. Résultat : 19/20 anomalies, 1/20 fausse alerte (démonstration, pas un chiffre de performance). Détails dans [README.md](README.md).

## Décisions prises
<!-- Une ligne par décision : AAAA-MM-JJ HH:MM — décision — raison. -->
- 2026-11-26 — Une **photo** au début de la prise de poste, comparée à la référence ; persistance 1.
- 2026-11-27 — **Une section = un poste = un fichier de poste** ; quatre sections (`press_cell`, `machine_cell`, `machine_cell_variant`, `electrical_bench`) sur les jeux `poste_*_5s_11`. Noms des zones et éléments en **anglais**.
- 2026-11-27 — Règles par section, d'après les README des jeux : tapis bleu interdit (press cell) ; passage central libre, tapis opérateur autorisé (machine cells) ; opérateur autorisé partout (electrical bench).
- 2026-11-27 — Personnes autorisées : `zone_allowed_labels` (une zone) ou `ignore_labels` (partout) ; boîte agrandie de 15 % (le tabouret sous l'opérateur assis était signalé).
- 2026-11-27 — Taille minimale d'un changement plafonnée à 150 pixels : un petit outil au sol passait sous le seuil de 1 % d'une grande zone.
- 2026-11-27 — Le zone « floor » du poste électrique exclut l'emplacement du tabouret, qui bouge quand l'opérateur s'assoit.
- 2026-11-27 — Seules les détections utiles sont dessinées (objets inconnus, personnes, objets en cause) : YOLO voyait la presse comme une « tv ».
- 2026-11-26 — **Normalité apprise** (moyenne + dispersion par pixel) sur les photos conformes et la référence ; mesure en **validation croisée** (une photo conforme mise de côté à chaque fois).
- 2026-11-26 — Le détecteur ne fait que **nommer** un changement, il ne déclenche jamais d'alerte seul.
- 2026-11-26 — Différence en **couleur**, luminosité compensée ; alignement SIFT + RANSAC ; aucune modification du contrat (`"<label>@<zone>"` dans `misplaced`).

## Questions ouvertes
<!-- Questions sur le besoin métier ou les données, à poser à l'équipe ou à Hutchinson. -->
- Machine cell `anomaly_01` : quel est l'objet manquant ? Le seul écart visible avec la référence est aussi présent sur toutes les photos conformes.
- Electrical bench : un document posé sur l'établi est-il autorisé (`good_03`) ?
- Press cell : le tapis bleu est-il bien interdit pendant le contrôle de prise de poste (« hypothèse à valider » selon le README) ?
- Les étiquettes sont indicatives : à faire confirmer avant de citer les chiffres.
- En production : une référence et quelques photos conformes par caméra.
- Contrat : un champ `foreign: list[str]` serait plus clair que `misplaced` (modification de `contracts.py`, à décider en équipe).
- Racine du dépôt : extra `workstation` à passer à `ultralytics>=8.4` ; ajouter `*.ts` au `.gitignore`.

## Résultats
Jeux `poste_*_5s_11`, validation croisée, YOLO26 COCO, seuils 0,4 / 0,7, CPU :
- press_cell 5/5 anomalies, 0/5 fausse alerte ; machine_cell 4/5, 0/5 ; machine_cell_variant 5/5, 0/5 ; electrical_bench 5/5, 1/5 ;
- total : 19/20 anomalies, 1/20 fausse alerte ; alignement : 0 échec ; ≈ 0,3 s par photo.
- Ce n'est **pas** un chiffre de performance : 10 photos synthétiques par section.
