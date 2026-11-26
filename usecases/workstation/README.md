# Cas d'usage `workstation` — écarts au poste de travail

## Rôle
Poste **presse + établi 5S** : au début de la prise de poste, une **photo** du poste est comparée à sa **référence**, pour repérer (a) **ce qui n'est pas à sa place** (désordre sur l'établi, outil absent du tableau) et (b) **tout objet ou toute personne** dans la **zone rouge** hachurée à côté de la presse.

**Données de référence (depuis le 26/11) : `presse_5S_20`**, 20 images synthétiques plus `reference.png` :

| Catégorie | Nombre |
|---|---|
| `good` | 5 |
| `disorder` | 7 |
| `zone_object` (cartons, chariot, transpalette) | 4 |
| `zone_person` (opérateur) | 4 |

Les étiquettes sont **indicatives**. Le jeu est rangé dans `<data-root>/raw/workstation/presse_5S_20/` et n'est jamais versionné. Les jeux précédents (`dataset_5S`, `poste1` / `poste2`) ont été abandonnés.

## Analyseur : une photo comparée à la normalité apprise

Classe `usecases.workstation.model:ZoneWorkstationAnalyzer`. [config.yaml](config.yaml) pointe vers le fichier de poste [stations/presse_5s.yaml](stations/presse_5s.yaml), seule source de vérité : vues, boîtes, photos conformes.

1. **Alignement sur la bonne vue** ([align.py](align.py)) : `reference.png` (vue « pilote ») ne correspond qu'à `good_001`, qui est la même image recadrée. **Toutes les autres photos**, y compris les anomalies du lot pilote, ont le cadrage « planche », dont la référence est `good/good_002.png` (**exclue de la mesure**). La photo est comparée à la vue qui s'aligne le mieux : les faux alignements obtiennent 47 à 80 correspondances, les bons 97 et plus. Échec partout : `alignment_failed`, donc `a_verifier`.
2. **Normalité apprise** ([normal.py](normal.py)) : moyenne et dispersion par pixel des photos conformes alignées, **référence comprise**. Un pixel n'a changé que s'il s'écarte de plus de `normal_k` (4) dispersions, et d'au moins `diff_threshold` (25 niveaux). Il faut au moins 2 photos par vue ; sinon la vue se compare à sa seule référence.
3. **Zones** : `zone_rouge` (ni objet ni personne) et `etabli` (rien de nouveau). L'arrière-plan de l'atelier, qui bouge d'une photo à l'autre, n'est **jamais** jugé.
4. **Emplacements** : `bacs_bleus`, `tournevis`, `pinces` sur le tableau. S'il a changé à plus de 25 %, l'outil n'est pas à sa place et va dans `missing`.
5. **Détecteur YOLO26 COCO** (activé par défaut) : il **nomme** les personnes (`person@zone_rouge`), mais ne déclenche jamais d'alerte seul.

| Fichier | Rôle |
|---|---|
| [stations/presse_5s.yaml](stations/presse_5s.yaml) | Les deux vues, leurs zones et emplacements, la raison attendue par type d'anomalie |
| [station.py](station.py) | Lecture du fichier de poste et de `labels.csv` (les deux formats d'étiquettes) |
| [align.py](align.py) / [normal.py](normal.py) / [zones.py](zones.py) | Alignement, normalité apprise, masques et changements |
| [model.py](model.py) / [detector.py](detector.py) | Analyseur et détecteur |
| [evaluate.py](evaluate.py) | Mesure en validation croisée (une photo conforme mise de côté à chaque fois), images annotées |
| [draw_zones.py](draw_zones.py) | Dessin de nouvelles zones à la souris (sur PC, fenêtre tkinter) |
| [make_samples.py](make_samples.py) | Poste synthétique dessiné, pour les tests unitaires |

### Mesurer
```bash
python -m usecases.workstation.evaluate --data-root ~/data --annotate      # --device cuda sur le cluster
```
Sortie dans `<data-root>/processed/workstation/presse_5s/` : `results.csv`, `preview_planche.png` / `preview_pilote.png` (boîtes sur chaque référence), `annotated/` (chaque photo alignée, avec les boîtes et le verdict).

### Résultats (26/11, CPU, seuils 0,4 / 0,7)
| | Sans détecteur | Avec YOLO26 COCO |
|---|---|---|
| Anomalies détectées, pour la bonne raison | 15/15 | 15/15 |
| Fausses alertes (photos conformes) | 0/4 | 0/4 |
| Personnes nommées dans la zone rouge | 0/4 | 2/4 (les deux du lot généré) |
| Latence | ≈ 0,4 s | ≈ 0,8 s |

**À dire au jury, ce n'est pas un chiffre de performance :**
- 20 images seulement, dont **4 conformes pour mesurer**, donc une erreur vaudrait 25 %. Ce sont des démonstrations, à présenter image par image.
- Les 5 anomalies du **lot pilote** sont bien détectées, mais avec des **signalements en trop** : leur zone rouge porte un pictogramme absent des photos de la planche, et leurs bacs diffèrent. Aucune photo conforme du lot pilote n'existe dans ce cadrage, donc les 0/4 fausses alertes **ne couvrent pas ce lot**.
- En production : une référence **et quelques photos conformes** par caméra et par configuration du poste.

### Tests
`pytest usecases/workstation` : tests unitaires sur le poste synthétique (sans données ni modèle), plus [tests/test_presse_5s.py](tests/test_presse_5s.py) qui vérifie sur le vrai jeu, s'il est présent, que chaque type d'anomalie est détecté (sinon ignoré, par exemple en CI ; `WORKSTATION_DATA_ROOT=~/data` sur le cluster).

## Contrat

**Entrée** : `analyze(image, meta)`
- `image` : `numpy.ndarray` BGR `uint8` de forme `(H, W, 3)`, déjà recadrée sur la zone d'intérêt (`ROI`).
- `meta` : `FrameMeta` (`frame_id`, `timestamp`, `workstation_id`, `camera_id`).

**Sortie** : un `AnalysisResult` avec `use_case="workstation"` et `details` de type `WorkstationDetails`. Schémas dans [visionhub/contracts.py](../../visionhub/contracts.py).

| Champ | Sens |
|---|---|
| `score` | dans [0, 1], **plus haut = écart plus grave**. À définir : par exemple 0 si tout est conforme, et des points ajoutés par objet manquant ou mal placé. |
| `details.expected` | objets attendus (la référence) |
| `details.detected` | objets détectés : `label`, `confidence`, boîte normalisée dans [0, 1] |
| `details.missing` | objets attendus mais absents |
| `details.misplaced` | objets présents mais hors de leur zone de référence |
| `latency_ms` | laisser à 0 : la chaîne d'analyse le mesure |

La couche de décision commune transforme le score en `conforme`, `a_verifier` ou `anomalie`. **N'appliquez pas de seuil vous-mêmes** : renvoyez le score brut.

Exemple d'événement produit (`GET /events?use_case=workstation`) :

```json
{
  "use_case": "workstation",
  "score": 0.507,
  "latency_ms": 42.3,
  "model_name": "fake-workstation",
  "model_version": "0.1.0",
  "details": {
    "kind": "workstation",
    "expected": ["screwdriver", "gauge", "parts_tray", "torque_wrench"],
    "detected": [
      {"label": "screwdriver", "confidence": 0.93, "bbox": {"x1": 0.02, "y1": 0.6, "x2": 0.22, "y2": 0.9}},
      {"label": "gauge", "confidence": 0.657, "bbox": {"x1": 0.376, "y1": 0.6, "x2": 0.576, "y2": 0.9}},
      {"label": "parts_tray", "confidence": 0.823, "bbox": {"x1": 0.52, "y1": 0.6, "x2": 0.72, "y2": 0.9}},
      {"label": "torque_wrench", "confidence": 0.747, "bbox": {"x1": 0.77, "y1": 0.6, "x2": 0.97, "y2": 0.9}}
    ],
    "missing": [],
    "misplaced": ["gauge"]
  },
  "event_id": "43c41a79-27c9-4098-9a98-785514cabb5f",
  "frame": {"frame_id": "CAM-01-000012", "timestamp": "2026-11-25T22:19:47.510130Z",
            "workstation_id": "WS-01", "camera_id": "CAM-01"},
  "decision": "a_verifier",
  "thresholds_used": {"low": 0.4, "high": 0.7},
  "operator_feedback": null
}
```

## Remplacer le faux analyseur par un vrai

1. **Installer la dépendance** :
   - sans Docker : `pip install -e ".[workstation]"` ;
   - avec Docker : `docker compose build --build-arg EXTRAS=dashboard,dev,workstation`.
2. **Ranger les poids** dans `data/models/workstation/` (dossier ignoré par Git, monté dans Docker).
3. **Créer `usecases/workstation/model.py`** :

   ```python
   from visionhub.analyzer import Analyzer
   from visionhub.contracts import AnalysisResult, BBox, DetectedObject, UseCase, WorkstationDetails


   class YoloWorkstationAnalyzer(Analyzer):
       use_case = UseCase.WORKSTATION
       name = "yolo-workstation"
       version = "0.1.0"

       def load(self, config):
           from ultralytics import YOLO               # heavy import HERE, not at module top
           self.model = YOLO(config["weights"])
           self.device = config["device"]            # "cpu" or "cuda"
           self.expected = config["expected_objects"]
           self.reference_zones = config.get("reference_zones", {})

       def analyze(self, image, meta):
           h, w = image.shape[:2]
           r = self.model.predict(image, device=self.device, verbose=False)[0]
           detected = [
               DetectedObject(
                   label=r.names[int(c)], confidence=float(p),
                   bbox=BBox(x1=x1 / w, y1=y1 / h, x2=x2 / w, y2=y2 / h),
               )
               for (x1, y1, x2, y2), c, p in zip(r.boxes.xyxy.tolist(), r.boxes.cls, r.boxes.conf)
           ]
           missing = [o for o in self.expected if o not in {d.label for d in detected}]
           misplaced = ...                           # compare to self.reference_zones
           score = ...                               # in [0, 1], from missing / misplaced
           return AnalysisResult(
               use_case=self.use_case, score=score,
               model_name=self.name, model_version=self.version,
               details=WorkstationDetails(expected=self.expected, detected=detected,
                                          missing=missing, misplaced=misplaced),
           )
   ```

4. **Changer une ligne dans `config.yaml`** et ajouter vos paramètres :

   ```yaml
   analyzer_class: usecases.workstation.model:YoloWorkstationAnalyzer
   params:
     weights: data/models/workstation/best.pt
     expected_objects: [screwdriver, gauge, parts_tray, torque_wrench]
   ```

5. **Vérifier** : `pytest tests/test_contract.py usecases/workstation/tests`. Le test de contrat doit passer en local, **avec vos poids**. Adaptez `tests/test_workstation.py`, qui teste le faux analyseur.
6. **Relancer la démo** : `docker compose restart api`, ou `python -m visionhub.demo`.

## Points d'attention
- **Définition de « mal placé »** : zone de référence par objet (boîte normalisée dans `config.yaml`) et tolérance. C'est à décider avec l'équipe et à noter dans `AGENTS.md`.
- **Boîtes normalisées** : divisez les coordonnées en pixels par la largeur et la hauteur de l'image.
- Ultralytics installe `opencv-python`, qui peut entrer en conflit avec `opencv-python-headless`. En cas d'erreur à l'import de `cv2` : `pip uninstall -y opencv-python opencv-python-headless && pip install opencv-python-headless`.
- Ultralytics peut **télécharger des poids automatiquement** (par exemple `yolov8n.pt`). Téléchargez-les une fois, à la main, dans `data/models/`, puis pointez dessus.
