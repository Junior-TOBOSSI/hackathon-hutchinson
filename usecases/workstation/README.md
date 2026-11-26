# Cas d'usage `workstation` — écarts au poste de travail

## Rôle
Vérifier que le **poste est configuré comme la référence** : chaque objet attendu (outils, bacs, gabarits…) est présent et à sa place, et aucun objet manquant n'est oublié. Piste : détection d'objets YOLO (Ultralytics), puis comparaison des détections à une liste et à des positions de référence.

## Analyseur actuel : zones à garder vides + détection (squelette)

Caméra **fixe, vue de dessus**. Classe : `usecases.workstation.model:ZoneWorkstationAnalyzer`, réglée dans [config.yaml](config.yaml).

| Fichier | Rôle |
|---|---|
| [zones.py](zones.py) | Masque de zone, recouvrement boîte/zone, différence **couleur** avec l'image de référence. NumPy/OpenCV, sans modèle |
| [detector.py](detector.py) | Détecteur : `none`, `coco` (YOLO26 COCO ou nos propres poids), `yoloe` (invites texte) |
| [model.py](model.py) | L'analyseur : identifie les éléments, cherche les objets dans les zones, persistance, score |
| [draw_zones.py](draw_zones.py) | Capture de la référence à la webcam et dessin des zones à la souris (local, tkinter) |
| [make_samples.py](make_samples.py) / [run_samples.py](run_samples.py) | Images synthétiques de test et affichage du verdict pour chacune |

Ce que fait l'analyseur pour chaque image :
1. **Identification** : le détecteur tourne sur toute l'image ; chaque objet va dans `details.detected`, et les éléments attendus non vus vont dans `details.missing`.
2. **Zones vides** : un objet détecté dont la boîte recouvre la zone à plus de `min_overlap` (15 %) est signalé avec son nom ; une région qui diffère de la référence et qu'aucune détection n'explique est signalée `unknown_object`. Les deux s'écrivent `"<label>@<zone>"` dans `details.misplaced`.
3. **Persistance** : un problème compte après `persistence_frames` images consécutives (3, soit 1,5 s à 2 images/s), pour qu'une main qui passe ne déclenche rien.
4. **Score** : celui du problème le plus grave (confiance de la détection, ou part de la zone couverte pour un objet inconnu).
5. **L'opérateur** (`person`) n'est jamais un « objet dans la zone », et sa boîte est exclue de la différence d'image.

### Démarrer
```bash
pip install -e ".[workstation]"            # puis : pip install "ultralytics>=8.4" (YOLO26)
yolo settings sync=False                   # aucune statistique envoyée à Ultralytics
python -m usecases.workstation.make_samples   # images synthétiques -> data/processed/workstation/synthetic
python -m usecases.workstation.run_samples    # verdict de chaque scénario et de la séquence
# Poste réel : référence (poste rangé, PERSONNE dans le champ) puis zones
python -m usecases.workstation.draw_zones --camera 0 --save data/workstation/reference.png
```
Démo sur la séquence synthétique : `SOURCE=folder SOURCE_PATH=data/processed/workstation/synthetic/sequence`.

Les images synthétiques testent la différence d'image, la géométrie et la persistance ; ce sont des formes, qu'un modèle COCO ne reconnaît pas. Pour tester le détecteur, il faut de **vraies photos** prises avec la caméra du poste.

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
