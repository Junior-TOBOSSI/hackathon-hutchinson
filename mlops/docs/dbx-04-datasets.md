# DBX-04 — Gestion des datasets

## 1. Principes

- **Source de vérité** : `<dataset_root>/<version>/manifest.json` dans le Volume Unity Catalog (`/Volumes/workspace/argos_poc/images` pour Quality Demo).
  - Toutes les lectures passent par la Files API et les métadonnées Unity Catalog : **jamais de SQL warehouse**.
  - Les tables Delta `annotations` et `dataset_versions` sont des miroirs écrits par le job d'entraînement ; seules leurs métadonnées sont lues.
- **Une version = un dossier autonome et immuable** (ses images et son manifeste). `synthetic-v1` (DBX-00) n'est jamais modifiée.
- **Les brouillons sont séparés des versions** : `_drafts/<id>/draft.json` et `_drafts/<id>/files/<sha256>.<ext>`. Une publication produit un nouveau dossier.
- **Aucune publication ne déclenche d'entraînement.** Le job Databricks lit son dataset dans sa définition (`--dataset-dir`), et HOVIS affiche cette valeur réelle (aujourd'hui `synthetic-v1`). Le choix du dataset d'entraînement sera traité avec DBX-05.

## 2. Garanties de versionnement

Ces garanties sont **imposées par l'API HOVIS**. Databricks ne rend pas un dossier de Volume immuable : un utilisateur disposant des droits pourrait le modifier directement.

| Garantie | Mécanisme |
|---|---|
| Une version publiée n'est jamais réécrite | Toutes les écritures utilisent `overwrite=False`. Lors d'une reprise, un fichier déjà présent n'est accepté que si son SHA-256 est celui attendu. |
| Une publication interrompue n'est jamais présentée comme une version | Le manifeste est écrit **en dernier**, après la relecture de chaque fichier et la vérification de son SHA-256. Un dossier sans manifeste est signalé « publication interrompue ». |
| Une seule publication à la fois par version | Le verrou `_locks/<version>.lock` est créé avec `overwrite=False`, puis relu pour vérifier un jeton unique. Un verrou détenu par un autre brouillon n'est jamais supprimé. |
| Reprise simple d'une publication | La même demande, depuis le même brouillon, reprend la copie. C'est idempotent : le manifeste est identique (même date de départ) et rien n'est écrasé ni supprimé. |
| Reproductibilité | Le manifeste porte la version parente et le SHA-256 de son manifeste, le SHA-256 de chaque image, les splits, la date de création et l'identifiant du brouillon. `build_manifest` est une fonction pure : les mêmes entrées produisent les mêmes octets. |
| Splits hérités préservés | Le split d'un élément hérité ne peut pas changer. Une image de la version parente, même exclue, ne peut pas être réimportée (doublon SHA-256) : une image de test ne peut donc pas passer en entraînement. |
| Traçabilité des annotations | `label_history`, `previous_label` et `review` (validée, corrigée, importée) pour chaque élément ; liste `excluded_items` ; résumé `changes`. |
| Référence d'évaluation | Toute modification touchant la validation ou le test positionne `evaluation_reference_changed`, avec le détail dans `evaluation_changes`. `split_fingerprints` contient une empreinte par split, calculée sur les couples (image, label). Deux évaluations ne sont comparables sur un split que si cette empreinte est identique ; un nom proche ne suffit pas. |

## 3. API (préfixe `/api/mlops`)

| Méthode et route | Rôle |
|---|---|
| `GET /models/{id}/datasets` | Index : versions (`DatasetRef` et métadonnées), publications incomplètes, brouillons. Cache de 60 s, `?fresh=true` disponible. |
| `GET /models/{id}/datasets/{v}` | Détail d'une version : effectifs, stratégie, empreintes, provenance, versions de modèle associées. |
| `GET /models/{id}/datasets/{v}/items` | Annotations paginées (24 par défaut, 48 au maximum), filtres `split`, `label`, `review`, `q`. |
| `GET /models/{id}/datasets/{v}/images/{file}` | Image servie par le backend, **uniquement si elle figure dans le manifeste** ; `..`, `code/`, `runs/` et `_drafts` sont refusés. Réponse en cache immuable. |
| `GET /models/{id}/dataset-tables` | Schéma, nombre de lignes et dernière écriture des tables Delta (métadonnées Unity Catalog). |
| `GET /models/{id}/training-dataset` | Dataset réellement configuré dans le job d'entraînement. |
| `POST /models/{id}/dataset-drafts` | Crée un brouillon à partir d'une version publiée. |
| `GET` / `DELETE /models/{id}/dataset-drafts/{d}` | Lit ou supprime un brouillon (seulement son dossier ; jamais pendant une publication). |
| `PATCH …/{d}/items` | `validate`, `relabel` (classification uniquement, classe existante), `exclude`, `reset`. |
| `POST …/{d}/import` | Import borné (multipart). |
| `DELETE …/{d}/imports/{sha}` | Retire une image importée. |
| `GET …/{d}/images/{sha}` | Image importée dans le brouillon. |
| `POST …/{d}/publish` (202) | Publication en tâche de fond. |
| `GET /dataset-jobs/{job}` | Avancement réel : phase (verrou, copie, vérification, manifeste) et `done` / `total`. |

**Import** :
- 50 fichiers au plus par envoi, PNG ou JPEG, 2 Mo par fichier, 25 Mo par requête, 4096 px de côté au plus ;
- chaque fichier est vérifié par Pillow, puis contrôlé contre les doublons SHA-256 ;
- label et split sont choisis explicitement ; aucune annotation automatique et aucun prétraitement ;
- l'interface envoie des lots de 5 fichiers et affiche l'avancement réel ;
- l'attestation « données synthétiques » est une **déclaration**, pas une garantie technique.

**Formats non pris en charge** : un manifeste dont le format d'annotation n'est pas `classification` s'affiche en lecture seule. La correction de label et l'import sont alors refusés.

## 4. Performance (règles de DBX-PERF-01 appliquées)

- **Index** : mis en cache par le cache de lecture du connecteur (60 s) et préchauffé. Ses lectures indépendantes (dossiers, brouillons, versions de modèle) sont faites en parallèle, dans une copie du contexte de la requête. Mesures : 0,01 à 0,1 s à chaud, 1,5 s après expiration du cache, 1,9 s en lecture forcée (6,8 s avant la mise en parallèle).
- **Manifestes** : gardés en mémoire pour toute la durée du processus, puisqu'une version est immuable. Une version donnée n'entraîne donc qu'un seul téléchargement de manifeste.
- **Images** :
  - rien n'est chargé avant l'ouverture de la section ;
  - 24 images par page, en `loading="lazy"` ;
  - cache immuable côté navigateur, et LRU de 512 images côté backend.
- **Invalidation ciblée** : `datasets:<modèle>` et le brouillon concerné sont invalidés après chaque modification ou publication. Les données restent affichées pendant leur actualisation.

**Règles pour les prochains développements** : passer par `connector._cached` (ou `dataset_store`) plutôt que par des appels directs ; ne jamais lire une table Delta pendant la navigation ; tout nouvel appel MLflow profite automatiquement du cache des identifiants (dépendance aux attributs internes de MLflow 3.18, avec repli, décrite dans `dbx-perf-01.md`).

## 5. Tables Delta : option B

`train_quality.py` écrit désormais **une version à la fois** (`replaceWhere dataset_version = '<v>'`) :
- relancer un entraînement sur la même version remplace seulement ses lignes (idempotent, sans doublon) ;
- les autres versions sont conservées ;
- la première écriture crée la table.

Le nom de version est validé avant d'être placé dans le prédicat. Ni l'algorithme, ni les hyperparamètres, ni les colonnes ne changent.

**Le code distant utilisé par le job n'a pas été remplacé.** `/Volumes/workspace/argos_poc/images/code/train_quality.py` reste la version DBX-00. Procédure prévue pour DBX-05 :

1. Vérifier les tests : `pytest mlops/tests/test_datasets.py -k delta`.
2. Téléverser **uniquement** le code, sans lancer de job. `python -m mlops.databricks_poc.run_training_job` téléverse **puis lance** le job : ne pas l'utiliser. À la place :
   ```
   python -c "from mlops.databricks_poc.common import workspace_client; from mlops.databricks_poc.run_training_job import upload_code; print(upload_code(workspace_client()))"
   ```
3. Changer `--dataset-dir` dans la définition du job (chantier DBX-05), puis lancer un entraînement **explicitement validé**.
4. Contrôler `dataset_versions` et `annotations` : une ligne par version, et aucune version écrasée.

## 6. Recette réelle (26/11/2026)

| Étape | Résultat |
|---|---|
| Intégrité de `synthetic-v1` avant | Manifeste `74ed087f…12e4`, 200 images conformes |
| Brouillon `54fe7617fb0c` | 3 validations dans le **train** (`train/OK/ok_002.png`, `train/NOK/nok_000.png`, `train/OK/ok_003.png`) |
| Publication de `synthetic-v2` | Réussie en 65 s : 200 copies, 200 relectures avec SHA-256, manifeste `019e804d…3250` écrit en dernier |
| Vérifications | Manifeste relu identique au job ; parent = `synthetic-v1` ; 200 images conformes ; `evaluation_reference_changed = false` ; empreintes de validation et de test identiques à v1 |
| `synthetic-v1` après | Manifeste et 200 images inchangés |
| Effets de bord | Aucune nouvelle exécution du job ; alias (champion v2, challenger v1) et version servie (v2) inchangés ; aucun verrou restant |

Les validations portent sur le train uniquement : les jeux de validation et de test de référence sont ainsi conservés. Aucune correction de label n'a été faite sur les données réelles, car les images synthétiques sont correctement annotées : corriger un label aurait introduit une erreur. La correction est couverte par les tests automatisés.

## 7. Limites

- Immuabilité imposée par l'API HOVIS uniquement (voir §2).
- Une publication interrompue se reprend, elle ne s'annule pas : rien n'est supprimé automatiquement.
- Les images importées n'ont pas de paramètres de génération (`brightness`, `noise` et `defect` valent `null`). Leur taille peut différer de 64×64 ; l'adaptation au pipeline d'entraînement relève de DBX-05 et des groupes IA.
- Les tâches de publication sont suivies en mémoire. Si la passerelle redémarre pendant une publication, le dossier apparaît « interrompu » et se reprend depuis son brouillon.
- `synthetic-v2` et son brouillon publié `54fe7617fb0c` sont conservés pour DBX-05.
