# Cas d'usage `safety` — EPI et usage du téléphone

## Rôle
Détecter **l'absence d'EPI** (casque, gilet, lunettes, gants) et **l'usage du téléphone** au poste. Piste : détection d'objets YOLO (Ultralytics), avec un modèle de personnes et d'EPI, puis association de chaque EPI à une personne.

**Vie privée, par conception** : le contrat ne contient **aucune donnée d'identité ni aucune image de visage**. Une personne n'est décrite que par sa position dans l'image et l'état de chaque EPI. `person_index` est un numéro **dans l'image courante**, pas un identifiant de suivi. Tout champ supplémentaire est refusé par la validation.

## Contrat

**Entrée** : `analyze(image, meta)`
- `image` : `numpy.ndarray` BGR `uint8` de forme `(H, W, 3)`, déjà recadrée (`ROI`) et anonymisée si `ANONYMIZE=true`.
- `meta` : `FrameMeta` (`frame_id`, `timestamp`, `workstation_id`, `camera_id`).

**Sortie** : un `AnalysisResult` avec `use_case="safety"` et `details` de type `SafetyDetails`. Schémas dans [visionhub/contracts.py](../../visionhub/contracts.py).

| Champ | Sens |
|---|---|
| `score` | dans [0, 1], **plus haut = risque plus grave**. Suggestion : le maximum, sur toutes les personnes, de la confiance « EPI absent » ou « téléphone détecté ». |
| `details.person_count` | nombre de personnes détectées |
| `details.persons[]` | pour chaque personne : `person_index`, `bbox` (optionnelle, normalisée), `helmet` / `vest` / `glasses` / `gloves` à `present`, `absent` ou `uncertain`, et `phone` (booléen) |
| `latency_ms` | laisser à 0 : la chaîne d'analyse le mesure |

La couche de décision commune transforme le score en `conforme`, `a_verifier` ou `anomalie`. **N'appliquez pas de seuil vous-mêmes** : renvoyez le score brut.

Exemple d'événement produit (`GET /events?use_case=safety`) :

```json
{
  "use_case": "safety",
  "score": 0.477,
  "latency_ms": 42.3,
  "model_name": "fake-safety",
  "model_version": "0.1.0",
  "details": {
    "kind": "safety",
    "person_count": 2,
    "persons": [
      {"person_index": 0, "bbox": {"x1": 0.02, "y1": 0.1, "x2": 0.42, "y2": 0.95},
       "helmet": "uncertain", "vest": "present", "glasses": "present", "gloves": "present", "phone": false},
      {"person_index": 1, "bbox": {"x1": 0.52, "y1": 0.1, "x2": 0.92, "y2": 0.95},
       "helmet": "present", "vest": "present", "glasses": "present", "gloves": "present", "phone": false}
    ]
  },
  "event_id": "4b744196-1d15-457b-8651-ae42ee0d6442",
  "frame": {"frame_id": "CAM-01-000000", "timestamp": "2026-11-25T22:19:47.544566Z",
            "workstation_id": "WS-01", "camera_id": "CAM-01"},
  "decision": "a_verifier",
  "thresholds_used": {"low": 0.4, "high": 0.7},
  "operator_feedback": null
}
```

## Remplacer le faux analyseur par un vrai

1. **Installer la dépendance** :
   - sans Docker : `pip install -e ".[safety]"` ;
   - avec Docker : `docker compose build --build-arg EXTRAS=dashboard,dev,safety`.
2. **Ranger les poids** dans `data/models/safety/` (dossier ignoré par Git, monté dans Docker).
3. **Créer `usecases/safety/model.py`** :

   ```python
   from visionhub.analyzer import Analyzer
   from visionhub.contracts import AnalysisResult, BBox, PersonPPE, PPEState, SafetyDetails, UseCase


   class YoloSafetyAnalyzer(Analyzer):
       use_case = UseCase.SAFETY
       name = "yolo-ppe"
       version = "0.1.0"

       def load(self, config):
           from ultralytics import YOLO               # heavy import HERE, not at module top
           self.model = YOLO(config["weights"])
           self.device = config["device"]            # "cpu" or "cuda"

       def analyze(self, image, meta):
           r = self.model.predict(image, device=self.device, verbose=False)[0]
           persons = []
           ...  # 1) person boxes  2) assign each PPE / phone box to a person (box overlap)
                # 3) present / absent / uncertain from the confidence
           score = ...                               # in [0, 1]
           return AnalysisResult(
               use_case=self.use_case, score=score,
               model_name=self.name, model_version=self.version,
               details=SafetyDetails(person_count=len(persons), persons=persons),
           )
   ```

4. **Changer une ligne dans `config.yaml`** et ajouter vos paramètres :

   ```yaml
   analyzer_class: usecases.safety.model:YoloSafetyAnalyzer
   params:
     weights: data/models/safety/best.pt
   ```

5. **Vérifier** : `pytest tests/test_contract.py usecases/safety/tests`. Le test de contrat doit passer en local, **avec vos poids**. Adaptez `tests/test_safety.py`, qui teste le faux analyseur. Gardez `test_no_identity_fields_in_contract`.
6. **Relancer la démo** : `docker compose restart api`, ou `python -m visionhub.demo`.

## Points d'attention
- **Ne jamais** sauvegarder de recadrage de personne ou de visage, même pour déboguer. Ne publiez aucune image de personne.
- **`uncertain`** sert quand le modèle hésite (EPI caché, personne de dos, confiance moyenne). C'est ce qui alimente la file « à vérifier ».
- **Gants et lunettes** sont de petits objets, difficiles à détecter : prévoyez de mesurer leur performance séparément.
- Ultralytics installe `opencv-python`, qui peut entrer en conflit avec `opencv-python-headless` (même correctif que dans les autres README). Il peut aussi télécharger des poids automatiquement : téléchargez-les une fois, à la main, dans `data/models/`.
