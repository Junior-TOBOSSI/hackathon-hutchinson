# Cas d'usage `workstation` — écarts au poste de travail

## Rôle
Contrôle **5S** au début de la prise de poste : une **photo** du poste est comparée à sa **référence**, pour repérer (a) **ce qui n'est pas à sa place** et (b) **tout objet ou toute personne non autorisée** dans une zone à garder libre. **Une section = un poste = un fichier de poste** dans [stations/](stations/).

| Section | Fichier | Jeu (`<data-root>/raw/workstation/`) | Zones | Éléments | Personne |
|---|---|---|---|---|---|
| Press cell | [press_cell.yaml](stations/press_cell.yaml) | `poste_5s_11` | `blue_mat`, `workbench` | `tool_tray`, `blue_bin`, `shelf_blue_bin`, `yellow_bin` | interdite sur le tapis |
| Machine cell (top view) | [machine_cell.yaml](stations/machine_cell.yaml) | `poste_bleu_5s_11` | `walkway`, `operator_mat` | `rack_bin`, `orange_crate` | autorisée sur `operator_mat`, interdite sur `walkway` |
| Machine cell variant | [machine_cell_variant.yaml](stations/machine_cell_variant.yaml) | `poste_variante_5s_11` | `passage`, `workbench` | `bench_blue_bin`, `rack_blue_bin`, `rack_yellow_bin` | interdite dans le passage |
| Electrical bench | [electrical_bench.yaml](stations/electrical_bench.yaml) | `poste_electrique_5s_11` | `floor`, `workbench` | `tool_tray`, `screwdrivers`, `blue_bins`, `cable_coil` | autorisée partout (opérateur au travail) |

Chaque jeu contient 1 référence, 5 photos conformes et 5 anomalies synthétiques, avec des étiquettes **indicatives** dans 4 formats de `labels.csv` différents (colonnes décrites par la clé `labels` de chaque fichier de poste). Les jeux ne sont jamais versionnés. Les jeux précédents (`presse_5S_20`, `dataset_5S`, `poste1` / `poste2`) ont été abandonnés.

## Analyseur : une photo comparée à la normalité apprise

Classe `usecases.workstation.model:ZoneWorkstationAnalyzer`. [config.yaml](config.yaml) donne les réglages communs et la section par défaut (`station`).

1. **Alignement** ([align.py](align.py)) : la photo est recalée sur la référence de sa section (SIFT + RANSAC ; 95 à 230 correspondances sur ces jeux). Échec : `alignment_failed`, donc `a_verifier`.
2. **Normalité apprise** ([normal.py](normal.py)) : moyenne et dispersion par pixel des photos conformes alignées, référence comprise. Un pixel n'a changé que s'il s'écarte de plus de `normal_k` (4) dispersions, et d'au moins `diff_threshold` (25 niveaux).
3. **Zones** : tout changement est un écart (`unknown_object@<zone>`, au moins `a_verifier`). La taille minimale d'un changement est 1 % de la zone, **plafonnée à 150 pixels**, pour voir un petit outil au sol dans une grande zone.
4. **Personnes autorisées** : `zone_allowed_labels` (autorisée dans une zone seulement) ou `ignore_labels` (autorisée partout). La boîte de la personne, agrandie de 15 % (tabouret, ombre), est retirée de la comparaison. Cela demande le détecteur YOLO26 : sans lui, l'opérateur du poste électrique est signalé.
5. **Emplacements** : s'il a changé à plus de 25 %, l'élément n'est pas à sa place et va dans `missing`.
6. **Détecteur YOLO26 COCO** : il ne fait que **nommer** (personnes surtout), ne déclenche jamais d'alerte seul. Ses autres détections (la presse vue comme une « tv ») ne sont pas affichées.

| Fichier | Rôle |
|---|---|
| [stations/](stations/) | Une annotation par section (zones, éléments, règles, colonnes de `labels.csv`), en anglais |
| [station.py](station.py) | Lecture d'un fichier de poste et de son `labels.csv` |
| [align.py](align.py) / [normal.py](normal.py) / [zones.py](zones.py) | Alignement, normalité apprise, masques et changements |
| [model.py](model.py) / [detector.py](detector.py) | Analyseur et détecteur |
| [render.py](render.py) | Boîtes redessinées sur la photo d'origine, bandeau OK / CHECK / NOK |
| [demo_app.py](demo_app.py) | Démo Streamlit : choix de la section, choix de la photo, verdict |
| [evaluate.py](evaluate.py) | Mesure en validation croisée, images annotées |
| [draw_zones.py](draw_zones.py) | Dessin de nouvelles zones à la souris (sur PC, fenêtre tkinter) |

### Démo visuelle (Streamlit)
```bash
streamlit run usecases/workstation/demo_app.py --server.port 8502 --server.address localhost --browser.gatherUsageStats false
```
En haut, un bouton par **section**. Dans le panneau latéral, la **photo** à évaluer (liste, précédente / suivante, lecture automatique). L'image affiche le verdict (**OK / CHECK / NOK**) et les boîtes (rectangles pour les éléments et les objets, vraie forme pour les zones) :
- **vert** : élément à sa place, zone libre ;
- **rouge** : élément absent ou déplacé, zone occupée ;
- **orange** : objet inconnu ;
- **violet** : personne.

À droite : le constat, la vérité terrain et si le verdict est juste. Chaque photo conforme est jugée par un modèle qui ne l'a pas apprise. C'est un outil de démonstration du binôme : le tableau de bord de l'équipe reste celui qui passe par l'API.

### Mesurer
```bash
python -m usecases.workstation.evaluate --station electrical_bench --data-root ~/data --annotate
```

### Résultats (27/11, validation croisée, YOLO26, seuils 0,4 / 0,7)
| Section | Anomalies détectées | Fausses alertes |
|---|---|---|
| Press cell | 5/5 | 0/5 |
| Machine cell | 4/5 | 0/5 |
| Machine cell variant | 5/5 | 0/5 |
| Electrical bench | 5/5 | 1/5 |
| **Total** | **19/20** | **1/20** |

Les deux erreurs viennent des données :
- **Machine cell `anomaly_01`** (« objet manquant ») : l'objet qui diffère de la référence (le bac bleu à ouverture noire de la machine) manque aussi sur les 5 photos conformes, donc l'anomalie est indiscernable d'une photo conforme.
- **Electrical bench `good_03`** (« conforme_document ») : une feuille posée sur l'établi donne CHECK. C'est un vrai changement en 5S ; il faut que le client dise si un document y est autorisé.

**Ce n'est pas un chiffre de performance** : 10 photos synthétiques par section, à présenter image par image.

### Tests
`pytest usecases/workstation` : tests unitaires sur un poste synthétique (sans données ni modèle), plus [tests/test_sections.py](tests/test_sections.py) qui rejoue chaque section si son jeu est présent (sinon ignoré, par exemple en CI ; `WORKSTATION_DATA_ROOT=~/data` sur le cluster).

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
