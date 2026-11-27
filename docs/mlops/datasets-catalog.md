# HOVIS — Catalogue de datasets indépendant (DBX-04-UI)

## Périmètre

La page **AI Leader → Datasets** consulte `GET /api/mlops/datasets`, sans sélectionner de modèle. Les familles historiques restent dans leurs dossiers et conservent les routes `GET /api/mlops/models/{model_id}/datasets` utilisées ailleurs. Une famille indépendante est enregistrée par `family.json` dans le Volume Unity Catalog existant, sous `ARGOS_DBX_DATASET_CATALOG_ROOT/{dataset_id}`. À défaut de variable explicite, le catalogue utilise `_families` sous le premier `dataset_root` configuré. Pour une exploitation indépendante de la configuration d'un modèle, définir explicitement `ARGOS_DBX_DATASET_CATALOG_ROOT` (dans le même Volume existant).

La lecture réutilise `DatasetStore`, la Files API, les manifestes immuables et le cache de lecture existants. Pour les familles indépendantes, `family.json` contient aussi une projection légère (dernière version, effectifs et date) actualisée après publication ; le manifeste reste la source de vérité et sert de repli si cette projection manque ou est incomplète. La liste des familles se lit avec quatre travailleurs au maximum. Le catalogue ne télécharge aucune image. Les images sont servies uniquement dans l'onglet **Échantillons**, par page et depuis la liste des fichiers autorisés par le manifeste. La création d'une famille ne crée aucun modèle, aucune version ni aucun job d'entraînement. Les brouillons et la publication réutilisent le mécanisme DBX-04 (copie, SHA-256, manifeste écrit en dernier, reprise).

## Routes ajoutées

| Méthode | Route relative à `/api` | Usage |
|---|---|---|
| GET / POST | `/mlops/datasets` | Catalogue / nouvelle famille |
| GET | `/mlops/datasets/{dataset_id}` | Index, versions, brouillons |
| GET | `/mlops/datasets/{dataset_id}/versions` | Versions publiées |
| GET | `/mlops/datasets/{dataset_id}/versions/{version}` | Détail d'une version |
| GET | `/mlops/datasets/{dataset_id}/versions/{version}/items` | Annotations paginées |
| GET | `/mlops/datasets/{dataset_id}/versions/{version}/images/{file}` | Image à la demande |
| POST | `/mlops/datasets/{dataset_id}/drafts` | Brouillon (parent nul pour la première version) |
| GET / DELETE | `/mlops/datasets/{dataset_id}/drafts/{draft_id}` | Consulter / supprimer un brouillon |
| PATCH | `/mlops/datasets/{dataset_id}/drafts/{draft_id}/items` | Valider, corriger ou exclure une annotation |
| POST | `/mlops/datasets/{dataset_id}/drafts/{draft_id}/import` | Import PNG/JPEG synthétiques attestés |
| DELETE | `/mlops/datasets/{dataset_id}/drafts/{draft_id}/imports/{sha}` | Retirer un import |
| GET | `/mlops/datasets/{dataset_id}/drafts/{draft_id}/images/{sha}` | Image de brouillon à la demande |
| POST | `/mlops/datasets/{dataset_id}/drafts/{draft_id}/publish` | Publication asynchrone |

Le suivi d'une publication utilise la route existante `GET /api/mlops/dataset-jobs/{job_id}`. Les routes historiques restent inchangées.

## Recette isolée

Depuis `C:\Users\GDYZ5751\Desktop\HOVIS_DATASETS`, utiliser deux terminaux PowerShell. Ne pas utiliser les ports de Claude (`8020`, `5174`) ni son worktree.

```powershell
$env:ARGOS_CORE_DB = 'var/hovis-datasets-core.sqlite3'
$env:MLFLOW_DISABLE_AGENT_HINT = '1'
$env:HOVIS_MLOPS_WARMUP = '0'
C:\Users\GDYZ5751\ARGOS_MLOPS_LOCAL\.venv\Scripts\python.exe -m uvicorn mlops.api.platform:app --host 127.0.0.1 --port 8023
```

```powershell
cd C:\Users\GDYZ5751\Desktop\HOVIS_DATASETS\argos-ui
$env:VITE_LIVE_AI_LEADER = 'true'
$env:ARGOS_API_TARGET = 'http://127.0.0.1:8023'
$env:NODE_OPTIONS = '--max-old-space-size=768'
npx vite --host 127.0.0.1 --port 5177 --strictPort
```

Page : `http://127.0.0.1:5177/ai-leader?section=datasets` (vérifier l'URL effective de l'application après connexion). API : `http://127.0.0.1:8023/api/mlops/datasets`. Le navigateur n'a aucun secret Databricks ; le backend emploie le profil local. Ne pas configurer `HOVIS_MLOPS_WARMUP=1` pour cette recette ciblée.

## Famille Presse 5S — inspection préalable, aucun transfert

Archive locale : `C:\Users\GDYZ5751\Downloads\presse_5S_20.zip`. SHA-256 : `147077147a8d98ea3f8a10034a22c8f7f6e9b466b00447d0a769849fe6d0f1f4`. Taille : 6 013 675 octets. Le test CRC ZIP et la lecture complète des 20 PNG réussissent. L'archive contient 23 membres : 20 PNG annotés, `labels.csv`, `README.txt`, `reference.png`. Aucun chemin de membre ne sort de l'archive. Les 20 PNG ont 496 × 325 pixels et aucun champ de métadonnées PNG. Les 20 empreintes sont distinctes. `reference.png` a la même empreinte que `good/good_001.png` ; elle reste une référence et ne compte pas comme un 21e échantillon.

Le CSV contient exactement 20 chemins d'image valides et quatre classes : `good` 5, `disorder` 7, `zone_object` 4, `zone_person` 4. Le README décrit un prototype synthétique : 6 images de « lot pilote valide » et 14 scènes recadrées d'une planche générée ; les labels sont indicatifs, la géométrie et l'échelle humaine ne sont pas calibrées. Cette déclaration ne prouve ni l'absence de visages ni l'absence d'informations industrielles confidentielles. Un détecteur automatique de visages a signalé des zones possibles sur 12 images, y compris des images `good` ; les formes circulaires de la presse peuvent être des faux positifs. Une revue humaine des 20 images reste nécessaire avant toute attestation ou import distant. Aucun OCR fiable n'était disponible ; les textes éventuellement visibles dans les pixels n'ont pas été certifiés. Aucun fichier de l'archive n'a été modifié, prétraité ou transféré.

La séparation prévue est une famille `presse-5s`, cas d'usage `workstation`, format `classification`, avec ces quatre labels, sous son propre dossier du Volume. `quality-synthetic`, `synthetic-v1` et `synthetic-v2` restent à leur emplacement actuel. Aucun modèle fictif ni entraînement n'est créé. Après validation humaine de l'inspection et autorisation explicite du transfert, créer la famille dans l'interface, puis créer un brouillon initial. Le formulaire actuel importe des PNG/JPEG par classe et split ; extraire localement l'archive sans modifier les images, exclure `reference.png`, sélectionner les 20 images selon `labels.csv`, puis choisir explicitement les splits. La publication vérifie les empreintes avant d'écrire le manifeste. **L'import direct du ZIP et l'affectation automatique des splits ne sont pas implémentés** : cette limite évite d'inventer une stratégie d'évaluation pour 20 images. Ce jeu est une démonstration de catalogue et d'annotation, pas un jeu d'entraînement industriel représentatif.

## Reprise par Claude

Intégrer uniquement la branche locale `feat/datasets-catalog` après revue. Fichiers partagés touchés : `mlops/api/routes.py`, `mlops/databricks/datasets.py`, `mlops/databricks/settings.py`, `argos-ui/src/api/mlops.ts`, `argos-ui/src/pages/ai-leader/common.tsx`, `argos-ui/src/pages/ai-leader/data.tsx`. La page `Datasets.tsx` et ses sous-composants sont dans le périmètre Datasets. Aucune modification de Training Factory, des modèles, d'AI Leader hors Datasets, des contrats industriels ou des données existantes. Les versions de modèle peuvent continuer à référencer un URI de dataset/version ; aucun couplage inverse obligatoire n'est ajouté.
