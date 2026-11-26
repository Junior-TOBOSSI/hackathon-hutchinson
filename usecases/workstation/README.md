# Cas d'usage `workstation` — écarts au poste de travail

## Rôle
Besoin client (26/11) : **au début de la prise de poste**, une **photo** du poste est comparée à **l'image de référence fournie par le client**, pour repérer (a) **ce qui n'est pas à sa place** et (b) **tout objet ou toute personne** dans une zone d'intérêt qui doit rester vide.

## Analyseur : une photo comparée à la référence

Classe `usecases.workstation.model:ZoneWorkstationAnalyzer`, réglée dans [config.yaml](config.yaml). Pour chaque photo :

0. **Alignement** ([align.py](align.py)) : la photo est recalée sur la référence (points SIFT + homographie RANSAC). En cas d'échec : `alignment_failed`, score 0,5, donc `a_verifier` (un humain regarde, le système ne devine pas).
1. **Identification** : le détecteur (`none` / `coco` / `yoloe`) tourne sur toute l'image ; chaque objet va dans `details.detected`.
2. **Changements** : un seul masque des pixels qui diffèrent de la référence (différence **couleur**, luminosité compensée), lu par les zones et les emplacements.
3. **Emplacements d'éléments** (`element_slots`) : si une part suffisante (`slot_min_change`, 25 %) de l'emplacement a changé, l'élément n'est pas à sa place et va dans `details.missing` (ou `misplaced` si le détecteur le voit ailleurs).
4. **Zones vides** (`empty_zones`) : un objet ou une personne détecté dans la zone, ou un changement qu'aucune détection n'explique (`unknown_object`), s'écrit `"<label>@<zone>"` dans `details.misplaced`. Score = la plus forte des deux preuves (confiance du détecteur, taille du changement), et au moins `unknown_min_score` (0,45, donc `a_verifier`) : « aucun élément » veut dire aucun.
5. **Score** : celui du problème le plus grave ; la couche de décision commune donne conforme / a_verifier / anomalie.

| Fichier | Rôle |
|---|---|
| [zones.py](zones.py) / [align.py](align.py) | Géométrie des zones, masque de changements, alignement |
| [detector.py](detector.py) / [model.py](model.py) | Détecteur et analyseur |
| [stations/](stations/) | Un fichier par poste : image source, zones vides, emplacements (coordonnées normalisées) |
| [clean_capture.py](clean_capture.py) | Capture de l'ancien système → référence propre (recadrage + effacement des incrustations) |
| [make_variants.py](make_variants.py) | Photos de test générées depuis la référence, avec la réponse attendue |
| [evaluate.py](evaluate.py) | Taux de détection, fausses alertes, latence ; images annotées |
| [draw_zones.py](draw_zones.py) | Dessin des zones à la souris (sur PC, fenêtre tkinter) |
| [make_samples.py](make_samples.py) / [run_samples.py](run_samples.py) | Poste synthétique dessiné, pour les tests automatiques |

### Données attendues (jamais versionnées)
```
<data-root>/raw/workstation/poste1_capture.png   # capture de l'ancien système
<data-root>/raw/workstation/poste2_atelier.png   # photo d'atelier (2e poste)
```
`<data-root>` vaut `data` sur PC, `~/data` sur le cluster.

### Générer et mesurer
```bash
python -m usecases.workstation.make_variants --station poste1 --data-root ~/data --n 10
python -m usecases.workstation.evaluate --station poste1 --data-root ~/data --detector none --annotate
# --detector coco pour ajouter YOLO26 ; --device cuda sur le cluster
```
Sortie dans `<data-root>/processed/workstation/poste1/` : `reference.png`, `preview.png` (zones en rouge, emplacements en cyan), `variants/` + `labels.json`, `results.csv`, `annotated/`.

Variantes générées (chacune avec un léger mouvement de caméra, de la lumière, du bruit et une compression JPEG) : `ok`, `object_outside` (conforme attendu), `missing_<emplacement>` (élément effacé par inpainting), `object_in_<zone>` (élément collé dans la zone), `person_in_<zone>` (personne découpée par YOLO26-seg, collée dans la zone).

### Premiers résultats (variantes générées, seed 0, 26/11)
| Poste | Détecteur | Alertes levées (bonne raison) | Fausses alertes | Latence CPU |
|---|---|---|---|---|
| poste1 | none | 24/24 | 0/20 | ~370 ms |
| poste1 | coco | 24/24 | 0/20 | ~760 ms |
| poste2 | none | 25/26 | 0/20 | ~390 ms |
| poste2 | coco | 25/26 | 0/20 | ~830 ms |

Limites connues : un objet **très petit** (quelques dizaines de pixels) ou de **même couleur que le sol** peut passer inaperçu (le seul raté du poste 2) ; `clean_capture` repère les incrustations par leur couleur, il ne convient que si la scène ne contient pas ce vert ou ce magenta vifs ; les variantes sont générées, pas réelles : à confirmer sur des photos du mini poste.

### Tests
`pytest usecases/workstation` : tests sur images synthétiques (sans modèle ni données), plus [tests/test_real_stations.py](tests/test_real_stations.py) qui traite **vos vraies images** s'il les trouve (sinon ignoré, par exemple en CI ; `WORKSTATION_DATA_ROOT=~/data` sur le cluster).

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
