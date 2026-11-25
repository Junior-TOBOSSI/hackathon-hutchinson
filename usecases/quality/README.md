# Cas d'usage `quality` — contrôle qualité des pièces

## Rôle
Détecter les **pièces non conformes** (rayures, manques, taches, déformations…) par **détection d'anomalies**. Le modèle apprend à quoi ressemble une pièce conforme, puis signale ce qui s'en écarte. Pistes : PatchCore ou EfficientAD avec Anomalib, entraînés uniquement sur des pièces conformes.

## Contrat

**Entrée** : `analyze(image, meta)`
- `image` : `numpy.ndarray` BGR `uint8` de forme `(H, W, 3)` (convention OpenCV), déjà recadrée sur la zone d'intérêt (`ROI`).
- `meta` : `FrameMeta` (`frame_id`, `timestamp`, `workstation_id`, `camera_id`).

**Sortie** : un `AnalysisResult` avec `use_case="quality"` et `details` de type `QualityDetails`. Schémas dans [visionhub/contracts.py](../../visionhub/contracts.py).

| Champ | Sens |
|---|---|
| `score` | dans [0, 1], **plus haut = plus anormal**. Typiquement : le score d'anomalie de l'image, normalisé. |
| `details.zones` | zones anormales : boîte normalisée dans [0, 1] et score par zone |
| `details.heatmap_ref` | référence optionnelle (chemin) vers une carte de chaleur. **Jamais l'image elle-même.** |
| `latency_ms` | laisser à 0 : la chaîne d'analyse le mesure |

La couche de décision commune transforme le score en `conforme`, `a_verifier` ou `anomalie` avec les seuils de `config.yaml`, réglables à chaud depuis le tableau de bord. **N'appliquez pas de seuil vous-mêmes** : renvoyez le score brut.

Exemple d'événement produit (`GET /events?use_case=quality`) :

```json
{
  "use_case": "quality",
  "score": 0.456,
  "latency_ms": 42.3,
  "model_name": "fake-quality",
  "model_version": "0.1.0",
  "details": {
    "kind": "quality",
    "zones": [
      {"bbox": {"x1": 0.223, "y1": 0.771, "x2": 0.351, "y2": 0.914}, "score": 0.456},
      {"bbox": {"x1": 0.563, "y1": 0.009, "x2": 0.778, "y2": 0.144}, "score": 0.354}
    ],
    "heatmap_ref": null
  },
  "event_id": "d285c805-6a40-40ca-bc15-64196f44e3e0",
  "frame": {"frame_id": "CAM-01-000014", "timestamp": "2026-11-25T22:19:47.122723Z",
            "workstation_id": "WS-01", "camera_id": "CAM-01"},
  "decision": "a_verifier",
  "thresholds_used": {"low": 0.4, "high": 0.7},
  "operator_feedback": null
}
```

## Remplacer le faux analyseur par un vrai

1. **Installer la dépendance** :
   - sans Docker : `pip install -e ".[quality]"` ;
   - avec Docker : `docker compose build --build-arg EXTRAS=dashboard,dev,quality`.
2. **Ranger les poids** dans `data/models/quality/` (dossier ignoré par Git, monté dans Docker).
3. **Créer `usecases/quality/model.py`** :

   ```python
   from visionhub.analyzer import Analyzer
   from visionhub.contracts import AnalysisResult, AnomalyZone, BBox, QualityDetails, UseCase


   class PatchCoreQualityAnalyzer(Analyzer):
       use_case = UseCase.QUALITY
       name = "patchcore"
       version = "0.1.0"

       def load(self, config):
           # Import heavy libraries HERE, not at the top of the file.
           from anomalib.models import Patchcore  # noqa: F401
           self.device = config["device"]            # "cpu" or "cuda"
           self.weights = config["weights"]          # from config.yaml params
           ...  # load the model once

       def analyze(self, image, meta):
           ...  # inference: anomaly score + anomaly map
           score = ...                               # normalized to [0, 1]
           zones = [AnomalyZone(bbox=BBox(x1=..., y1=..., x2=..., y2=...), score=...)]
           return AnalysisResult(
               use_case=self.use_case, score=score,
               model_name=self.name, model_version=self.version,
               details=QualityDetails(zones=zones),
           )
   ```

4. **Changer une ligne dans `config.yaml`** et ajouter vos paramètres :

   ```yaml
   analyzer_class: usecases.quality.model:PatchCoreQualityAnalyzer
   params:
     weights: data/models/quality/patchcore.ckpt
   ```

5. **Vérifier** : `pytest tests/test_contract.py usecases/quality/tests`. Le test de contrat doit passer en local, **avec vos poids**. Adaptez `tests/test_quality.py`, qui teste le faux analyseur.
6. **Relancer la démo** : `docker compose restart api`, ou `python -m visionhub.demo`.

Pour tester sur des images réelles sans caméra : `SOURCE=folder` et `SOURCE_PATH=data/test/quality` dans `.env`. Vous pouvez aussi envoyer une image à `POST /analyze?use_case=quality` depuis <http://localhost:8000/docs>.

## Points d'attention
- **Normaliser le score** dans [0, 1] de façon stable. Par exemple, avec un min/max mesuré sur un jeu de validation conforme. Notez la méthode dans `AGENTS.md`.
- **Seuils** : choisissez `low` et `high` sur un jeu de validation, **jamais sur `data/test/`**.
- Anomalib installe `opencv-python`, qui peut entrer en conflit avec `opencv-python-headless`. En cas d'erreur à l'import de `cv2` : `pip uninstall -y opencv-python opencv-python-headless && pip install opencv-python-headless`.
- Le faux analyseur reste disponible : remettez l'ancienne ligne `analyzer_class` pour revenir en arrière.
