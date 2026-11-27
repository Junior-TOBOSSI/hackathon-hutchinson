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
