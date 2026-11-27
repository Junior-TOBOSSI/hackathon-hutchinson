# SCI-02-FINAL — intégration scientifique dans HOVIS

## État du 27 novembre 2026

Les deux pipelines sont déclarés dans Training Factory. Les scripts scientifiques des
groupes restent intacts. Le lancement distant demeure verrouillé par
`HOVIS_TRAINING_REMOTE` et les nouveaux Jobs ne sont pas créés. Aucune exécution
scientifique ni version de modèle n'est revendiquée pour ces nouveaux pipelines.

| Pipeline | Données | Résultat réel |
| --- | --- | --- |
| `quality-industrial-binary` | 839 images originales, 471 OK / 368 NOK, 29 rafales, cinq plis locaux | Préparé hors Git ; non publié dans Unity Catalog |
| `quality-industrial` (trois classes) | `tri_nok.csv` original absent | Conservé, mais bloqué pour les classes NOK distinctes |
| `workstation-industrial` | Quatre jeux de onze images du groupe absents | Code, quatre configurations et adaptateur intégrés ; aucun run réel |

Dans Datasets, les familles absentes portent un libellé *attendu* distinct des
versions publiées. Training Factory ne les propose comme choix de dataset que
lorsqu'un vrai manifeste est publié. Une absence de Job ou un manifeste non conforme
interdit le lancement. Une version de Model Registry n'est créée qu'après un run réel.

## Quality

L'archive source `ARGOS_DATA/data_train/Dataset.zip` a l'empreinte SHA-256
`eb6922a6f7018339608fca98ecd83dcf1c240eabbc3901f819ccd19fc3b4841b`.
Le script `mlops.datasets_prep.quality_702_binary` vérifie cette empreinte, les 839
images et leur annotation binaire originale, puis appelle le répartiteur inchangé
du groupe cinq fois. Les manifestes comprennent SHA-256 par image, rafale, split et
classe. Les cinq plis passent `dataset_checks` sans erreur ; aucune rafale ne fuit
entre train, validation et test. R05 (51 images NOK) reste incluse, sans décision
d'exclusion. Le pli 0 est la première expérience prévue ; aucune sélection sur le
test n'a été faite.

Les artefacts sont **privés et locaux** dans
`C:\Users\GDYZ5751\ARGOS_MLOPS_LOCAL\sci-01\data\quality`. Ils ne sont pas dans Git
et ne sont pas encore dans Databricks. Pour régénérer ou contrôler sans transfert :

```powershell
Set-Location C:\Users\GDYZ5751\Desktop\HOVIS_UNIFIED
$py = 'C:\Users\GDYZ5751\ARGOS_MLOPS_LOCAL\.venv\Scripts\python.exe'
& $py -m mlops.datasets_prep.quality_702_binary --archive 'C:\Users\GDYZ5751\Desktop\ARGOS_DATA\data_train\Dataset.zip' --output-root 'C:\Users\GDYZ5751\ARGOS_MLOPS_LOCAL\sci-01\data\quality'
```

Les fichiers `manifest.catalog-draft.json` de chaque pli sont des brouillons, pas
des versions publiées. **Le point de blocage actuel est précis :** l'import Datasets
existant (`DatasetStore.import_files`) exige une attestation `synthetic_attested`
et refuse les images industrielles. Il serait faux de cocher cette attestation pour
ces 839 images. Aucun transfert n'a donc été effectué. La publication requiert un
chemin d'import industriel distinct, avec autorisation explicite et contrôle final
des empreintes, sur un Volume autorisé, pour les versions `binary-pli0` à
`binary-pli4`. Le Job
`hovis-quality-industrial-binary-training` doit ensuite utiliser le launcher
`/Shared/ARGOS-POC/run_volume_script` et le script indiqué dans `pipeline.yaml`.
Le poids de départ `yolo26n-cls.pt` est public ; ce n'est **pas** le poids entraîné
du groupe. Le runner réutilise ses scripts `train.py`, `evaluer.py` et
`export_onnx.py`, garde le test indépendant et vérifie dynamiquement deux sorties
de classes pour l'ONNX binaire. Aucune performance ONNX réelle n'est annoncée.

Les 15 rafales NOK ont seulement leur annotation binaire originale. Le fichier
`tri_nok.csv` à trois classes n'a pas été livré et aucun type (`SANS`, `DOUBLE`,
`HORS_CADRE`) n'a été inventé. Les propositions locales demeurent `INCERTAIN` tant
qu'une preuve visuelle et métier fiable n'est pas disponible. Le script trois
classes du groupe et son pipeline existant restent prêts pour le CSV vérifié.

## Workstation

Le kit `mlops/pipelines/workstation/kit/usecases/workstation/` reprend les sources
scientifiques de `origin/integration` (`23c8e98`) et la configuration du groupe
`origin/workstation` (`f168032`) : `model.py`, `normal.py`, `align.py`,
`detector.py`, `zones.py`, `station.py`, `evaluate.py`, `render.py`,
`config.yaml`, les quatre YAML de `stations/`, `analyzer.py`, `demo_app.py`,
`draw_zones.py`, `make_samples.py` et les quatre tests. Les fichiers scientifiques
déjà présents ont été comparés octet par octet ; ils ne divergent pas. Le faux
analyseur `analyzer.py` n'est inclus que pour conserver les tests du groupe, et
n'est pas utilisé par `workstation-industrial`.

L'adaptateur `run_pipeline.py` vérifie la famille, la section et chaque SHA-256,
matérialise le jeu original dans la structure attendue par les YAML, puis appelle
`evaluate()` sans changer SIFT/RANSAC, la normalité statistique, les zones, les
emplacements ou la détection YOLO26 COCO. Il enregistre les métriques calculées,
`results.csv`, les images annotées, les aperçus et un modèle candidat MLflow dont
le chargement reconstruit la normalité à partir des images conformes originales.
L'API Training Factory expose ces résultats, avec un rendu Workstation spécifique
pour ne pas appeler « rappel NOK » une métrique d'anomalies de poste.

Fichiers encore à recevoir du groupe : pour chacun des dossiers
`poste_5s_11`, `poste_bleu_5s_11`, `poste_variante_5s_11`,
`poste_electrique_5s_11`, **`reference.png`, `labels.csv`, cinq photos
conformes et cinq photos d'anomalies** nommées dans le CSV. Les annotations des
types d'anomalies proviennent exclusivement du CSV du groupe ; les zones et
références sont définies dans les YAML inchangés. L'ancien `presse_5S_20.zip`
n'est pas un substitut à cette dernière livraison.

Préparer localement dès réception, sans transfert :

```powershell
Set-Location C:\Users\GDYZ5751\Desktop\HOVIS_UNIFIED
$py = 'C:\Users\GDYZ5751\ARGOS_MLOPS_LOCAL\.venv\Scripts\python.exe'
& $py -m mlops.datasets_prep.workstation_group --source-root 'C:\chemin\du\groupe\raw\workstation' --output-root 'C:\Users\GDYZ5751\ARGOS_MLOPS_LOCAL\prep\workstation-group'
```

Chaque section produit un manifeste `group-v1` avec ses vrais fichiers, empreintes,
annotations, identifiant de configuration et statut `synthetic=true` pour les
anomalies créées par le groupe. La publication future doit préserver `assets`
(référence et CSV) dans le Volume et les chemins du manifeste ; l'import Datasets
actuel ne prend pas en charge ces assets et exige donc un import spécialisé. Le Job
`hovis-workstation-training` doit utiliser le launcher et le script du
`pipeline.yaml` ; le poids public YOLO26 COCO doit être présent au chemin déclaré.
La création du Job et la copie du code/poids sont des opérations distantes non
effectuées ici. Un lancement sans ces prérequis reste bloqué.

## Vérification et sécurité

- `ruff check .` : propre.
- `pytest mlops/tests` et `pytest tests` : réussis avec
  `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`.
- Tests scientifiques Workstation : réussis hors données de groupe, avec quatre
  tests marqués `skip` car ils requièrent ces fichiers.
- `npm run build` : TypeScript et Vite réussis.
- Cinq manifestes Quality réels : 839 images chacun, 29 rafales, aucun contrôle
  bloquant. Aucun entraînement ou transfert réalisé.

La publication Git exclut ZIP, images, annotations individuelles, poids,
SQLite, secrets et credentials. Le verrou distant est conservé. Les données
industrielles restent hors dépôt. Un vrai chargement ONNX/Workstation et les
métriques scientifiques devront être constatés après livraison des prérequis,
publication des données autorisée et décision distincte sur l'exécution distante.

## Reprise et finalisation (Claude, après l'arrêt de Codex)

Le travail de Codex était déjà committé et publié (`54d2508`) : aucune modification n'a été perdue. La reprise le complète sur les points suivants.

### Workstation : une seule implémentation
- **Avant :** `usecases/workstation`, l'analyseur chargé par le Production Engine, était encore l'ancien squelette.
- **Maintenant :**
  - il est repris fichier par fichier depuis la livraison du groupe sur `origin/integration` (`a62a69b` ; les fichiers scientifiques sont inchangés depuis `23c8e98`) ;
  - son code (`*.py`, configurations des postes) est **identique à l'octet près** au kit MLOps. Le test `test_mlops_workstation_kit_is_byte_identical_to_the_run_analyzer` échoue au moindre écart ; `config.yaml` ne peut différer que par la ligne `analyzer_class`.
- **Analyseur par défaut côté RUN :** le faux analyseur fourni par le groupe (`usecases.workstation.analyzer:FakeWorkstationAnalyzer`). Le vrai `ZoneWorkstationAnalyzer` exige `ultralytics` et les images des postes, non livrées : l'activer par défaut cassait le test de contrat et les tests du pipeline. Pour l'activer, remplacer la ligne `analyzer_class` par `usecases.workstation.model:ZoneWorkstationAnalyzer` (commentaire dans `config.yaml`).

### Publication industrielle : `mlops/datasets_prep/publish_industrial.py`
- **Principe :** chemin d'import distinct de l'import Datasets, qui exige une attestation « synthétique ».
- **Mêmes garanties que le catalogue :**
  - verrou de publication ;
  - aucune réécriture (`overwrite=False`) ;
  - SHA-256 vérifié après chaque envoi ;
  - manifeste écrit en dernier ;
  - verrou retiré à la fin.
- **Par défaut : essai à blanc.** Il comprend les contrôles locaux et des vérifications distantes en lecture seule.
- **Transfert réel :** il exige `--execute`, `HOVIS_INDUSTRIAL_TRANSFER=1` et `--confirm <famille>/<version>`.
- **Essai à blanc réel, pli 0 :**
  - 839 images ; empreintes, labels et effectifs vérifiés ; 29 rafales sans fuite ;
  - cible : `/Volumes/workspace/argos_poc/images/_families/quality-industrial-binary/binary-pli0` (famille et version absentes) ;
  - **rien n'a été transféré.**

### Installation des Jobs : `mlops/training/install_job.py`
- **Principe :** la définition est copiée du job éprouvé `hovis-quality-industrial-training` (launcher, serverless CPU, sans planification, sans relance, un seul run à la fois). Seuls changent le nom, le script et l'environnement figé déclaré par `pipeline.yaml`.
- **Envoi du code :** le code du runner est envoyé dans `code_root`.
- **Par défaut : essai à blanc.** L'exécution exige `--execute`, `HOVIS_TRAINING_REMOTE_SETUP=1` et `--confirm <nom du job>`.
- **Aucun lancement :** installer un job ne le lance jamais.
- **Essai à blanc réel :**
  - `hovis-quality-industrial-binary-training` : job absent, poids `yolo26n-cls.pt` présents, runner présent.
  - `hovis-workstation-training` : job absent, **poids `yolo26n.pt` ABSENTS du Volume**.

### Annotations Quality en trois classes : non reconstituées
Je n'ai **pas** examiné les images. Pour les visualiser, mes outils doivent les transmettre à l'API cloud du fournisseur du modèle. Cela enfreint `AGENTS.md` (« aucune donnée ne part vers un service externe ») et l'interdiction de transférer des données industrielles.

Je n'ai pas non plus déduit d'annotations à partir des noms de fichiers ou des effectifs. Le fichier `tri_nok.reconstructed.csv` n'a donc pas été produit.

Deux voies sont conformes :
1. **Revue humaine locale** avec l'outil préparé par Codex (`ARGOS_MLOPS_LOCAL/sci-01/quality-review.html` et les planches de contact locales). Le résultat alimente `tri_nok.csv`, que contrôle `sci-01/validate_tri.py`.
2. **Autorisation écrite explicite** d'envoyer ces images au fournisseur du modèle pour une revue assistée. Les annotations produites seraient alors étiquetées « reconstituées », jamais « originales ».

En attendant, le pipeline **binaire** (`quality-industrial-binary`) n'est pas bloqué.

### Commandes (dans l'ordre ; chaque étape distante requiert votre autorisation)
```powershell
Set-Location C:\Users\GDYZ5751\Desktop\HOVIS_UNIFIED
$py = 'C:\Users\GDYZ5751\ARGOS_MLOPS_LOCAL\.venv\Scripts\python.exe'
$q  = 'C:\Users\GDYZ5751\ARGOS_MLOPS_LOCAL\sci-01\data\quality'
# 1. Publication du pli 0 (essai à blanc, puis transfert autorisé)
& $py -m mlops.datasets_prep.publish_industrial --prepared "$q\dataset_702_binary_pli0"
$env:HOVIS_INDUSTRIAL_TRANSFER = '1'
& $py -m mlops.datasets_prep.publish_industrial --prepared "$q\dataset_702_binary_pli0" --execute --confirm quality-industrial-binary/binary-pli0 --family-name "Qualité 702 binaire"
# 2. Installation du Job (essai à blanc, puis création autorisée)
& $py -m mlops.training.install_job --pipeline quality-industrial-binary
$env:HOVIS_TRAINING_REMOTE_SETUP = '1'
& $py -m mlops.training.install_job --pipeline quality-industrial-binary --execute --confirm hovis-quality-industrial-binary-training
# 3. Lancement : uniquement depuis Training Factory (TrainingService.launch), avec
#    $env:HOVIS_TRAINING_REMOTE = '1' positionné avant le démarrage de la passerelle.
# Workstation, après réception des 4 jeux : workstation_group (voir plus haut), publication
#    de chaque section, envoi de yolo26n.pt dans runs/hovis/weights/, puis
#    install_job --pipeline workstation-industrial.
```

## Métriques de décision Quality (Exactitude, F1 NOK…)
- **Source :** le fichier `evaluation/predictions.csv` produit par `evaluer.py` du groupe, une ligne par photo de test. Aucun modèle n'est relancé et aucun seuil n'est modifié (`mlops/pipelines/quality_industrial/decision_metrics.py`).
- **Convention (NOK = positif, cohérente avec `metriques.json` du groupe) :** TP = NOK→NOK, FN = NOK→OK, TN = OK→OK, FP = OK→NOK. Le verdict `A_VERIFIER` est compté à part (`a_verifier_nok`, `a_verifier_ok`) et reste dans les dénominateurs. Il n'est donc jamais compté comme correct.
  - exactitude = (TP + TN) / n ;
  - précision NOK = TP / (TP + FP) ;
  - rappel NOK = TP / n_NOK, soit le `rappel` du groupe ;
  - taux de faux rejets = FP / n_OK, soit les `faux_rejets` du groupe ;
  - métriques par classe sur les mêmes colonnes que la matrice de confusion affichée.
- **Runs futurs :** les clés `test_accuracy`, `test_precision_nok`, `test_recall_nok`, `test_f1_nok`, `test_false_reject_rate`, `test_tp/tn/fp/fn`, `test_a_verifier_*` et `test_class_<classe>_*` sont journalisées dans MLflow. Il faut d'abord renvoyer `run_pipeline.py` et `decision_metrics.py` dans le `code_root` du Volume (`install_job --execute`, ou un envoi de ces deux fichiers).
- **Runs historiques :** les métriques manquantes sont calculées à la lecture depuis l'artefact du run et marquées `hovis.metrics_derived_from`. Le run MLflow n'est jamais modifié.
- **Monitoring :** « Faux rejets » et « Défauts manqués » affichent désormais des nombres (FP, FN), et non plus des taux affichés comme des entiers.
