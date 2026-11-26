# Cas d'usage `workstation` — écarts au poste de travail

## Rôle
Poste de travail **5S** : au début de la prise de poste, une **photo** du poste est comparée à sa **référence**, pour repérer (a) **ce qui n'est pas à sa place** (désordre sur le plan de travail, outil absent du tableau) et (b) **tout objet ou toute personne** dans la **zone interdite**.

**Données de référence (depuis le 26/11) : `dataset_5S_80_496x325`**, un prototype synthétique : 1 référence, 30 photos conformes, 50 anomalies (38 désordres, 12 violations de zone). Étiquettes **indicatives, non validées** par le client. Le jeu est rangé dans `<data-root>/raw/workstation/dataset_5S_80_496x325/` et n'est jamais versionné.

## Analyseur : une photo comparée à la normalité apprise

Classe `usecases.workstation.model:ZoneWorkstationAnalyzer`. [config.yaml](config.yaml) pointe vers le fichier de poste [stations/dataset_5s.yaml](stations/dataset_5s.yaml), seule source de vérité : vues, boîtes, photos conformes.

1. **Alignement sur la bonne vue** ([align.py](align.py)) : le jeu mélange **deux cadrages**. Le cadrage A est net, comme la référence fournie. Le cadrage B est plus serré, flou, avec un bac vert et un câble sur l'établi. Une photo B ne s'aligne pas sur la référence A. Chaque cadrage a donc sa référence (B : `good/good_017.png`, **exclue de la mesure**) et ses boîtes, et la photo est comparée à la vue qui s'aligne le mieux. Échec partout : `alignment_failed`, donc `a_verifier`.
2. **Normalité apprise** ([normal.py](normal.py)) : une seule image ne suffit pas, car les photos conformes diffèrent déjà entre elles (bac décalé, hachures rendues autrement, panneau présent ou non). Pour chaque pixel, on retient la **moyenne** et la **dispersion** des photos conformes alignées. Un pixel n'a changé que s'il s'écarte de plus de `normal_k` (4) dispersions, et d'au moins `diff_threshold` (25 niveaux).
3. **Zones** : `zone_interdite` (ni objet ni personne) et `plan_de_travail` (rien de nouveau sur l'établi). Tout changement y devient `unknown_object@<zone>`, avec un score d'au moins 0,45 (`a_verifier`).
4. **Emplacements** : un emplacement par groupe d'outils du tableau (`cles`, `tournevis`, `pinces`, `marteau`, `metre`…). S'il a changé à plus de 25 %, l'outil n'est pas à sa place et va dans `missing`.
5. **Détecteur** (optionnel, `none` par défaut) : il ne fait que **nommer** un changement, il ne déclenche jamais d'alerte seul. Sur ce jeu, YOLO26 COCO n'a rien nommé de plus et doublait la latence.

| Fichier | Rôle |
|---|---|
| [stations/dataset_5s.yaml](stations/dataset_5s.yaml) | Les deux vues, leurs zones et emplacements (coordonnées normalisées) |
| [station.py](station.py) | Lecture du fichier de poste, du jeu étiqueté et des photos conformes |
| [align.py](align.py) / [normal.py](normal.py) / [zones.py](zones.py) | Alignement, normalité apprise, masques et changements |
| [model.py](model.py) / [detector.py](detector.py) | Analyseur et détecteur optionnel |
| [evaluate.py](evaluate.py) | Mesure en **validation croisée**, images annotées |
| [draw_zones.py](draw_zones.py) | Dessin de nouvelles zones à la souris (sur PC, fenêtre tkinter) |
| [make_samples.py](make_samples.py) | Poste synthétique dessiné, pour les tests unitaires |

### Mesurer
```bash
python -m usecases.workstation.evaluate --data-root ~/data --annotate      # --device cuda sur le cluster
```
**Validation croisée en 5 groupes** : une photo conforme n'est jamais jugée par un modèle qui l'a vue pendant l'apprentissage. Sortie dans `<data-root>/processed/workstation/dataset_5s/` : `results.csv`, `preview_A.png` / `preview_B.png` (boîtes sur chaque référence), `annotated/` (chaque photo alignée, avec les boîtes et le verdict).

### Résultats (26/11, CPU du PC de dev, seuils 0,4 / 0,7, sans détecteur)
| | Résultat |
|---|---|
| Anomalies détectées | **50/50** (100 %), toutes pour la bonne raison |
| Fausses alertes | **1/29** (3 %) : `good_029`, dont le bac bleu est nettement décalé (écart 5S discutable) |
| Échecs d'alignement | 0 |
| Latence | ≈ 0,25 s par photo |

Limites à dire au jury : le jeu est **synthétique** et petit (29 photos conformes), avec des étiquettes indicatives ; les réglages ont été choisis au milieu d'une plage stable (k = 3 à 4) pour ne pas coller aux données ; à confirmer sur des photos réelles.

### Tests
`pytest usecases/workstation` : tests unitaires sur le poste synthétique (sans données ni modèle), plus [tests/test_dataset_5s.py](tests/test_dataset_5s.py) qui rejoue la mesure sur le vrai jeu s'il est présent (sinon ignoré, par exemple en CI ; `WORKSTATION_DATA_ROOT=~/data` sur le cluster).

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
