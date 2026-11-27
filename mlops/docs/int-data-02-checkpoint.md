# INT-DATA-02 — état sauvegardé avant INT-MLOPS-02

Le code scientifique Workstation et ses quatre configurations ont été copiés **sans
modification** depuis `f1680324858e9184a797e27bbb0b9432df468598` vers
`mlops/pipelines/workstation/kit/usecases/workstation/`. Le `config.yaml` du Production
Engine n'a pas changé. Aucun modèle Workstation n'a été entraîné ou exécuté ici.

L'audit local Quality (`python -m mlops.datasets_prep.quality_702 --zip
C:\Users\GDYZ5751\Desktop\ARGOS_DATA\data_train\Dataset.zip`) produit un manifeste
de **source**, hors Git, dans `%USERPROFILE%\ARGOS_MLOPS_LOCAL\prep\quality-702\`.
Il compte 839 JPG : 471 OK et 368 NOK, 29 rafales selon le seuil de 3 secondes du
script scientifique, R05 = 51 NOK, zéro doublon exact. Il laisse chaque split
`unassigned` et `publishable=false`. Il ne classe pas les NOK en `NOK_SANS` et
`NOK_DOUBLE` et ne décide pas l'exclusion R05.

Fichiers encore nécessaires :

- Quality : `tri_nok.csv` rempli par le groupe, avec une ligne par rafale NOK et la
  décision métier sur R05. Les annotations manquantes empêchent le manifeste à trois
  classes et les splits définitifs.
- Workstation : quatre dossiers complets `poste_5s_11`, `poste_bleu_5s_11`,
  `poste_variante_5s_11`, `poste_electrique_5s_11` sous `raw/workstation/` ; **chacun**
  doit contenir `reference.png`, son `labels.csv`, cinq images conformes et cinq
  images d'anomalie. Les noms exacts des dix images proviennent de chaque `labels.csv`.
  Les quatre formats de CSV sont mappés par les fichiers `stations/*.yaml` du groupe.

Ce checkpoint ne crée pas de famille Databricks, de job, de run MLflow ni de version
Unity Catalog. La préparation du pipeline et des manifestes Workstation reste à faire
sur ces sources, sans changer le protocole de validation croisée du groupe. Une revue
de confidentialité et la confirmation de transfert doivent être archivées avec la
publication effective.
