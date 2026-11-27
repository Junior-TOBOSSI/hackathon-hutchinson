# SCI-03 — Intégration effective des datasets Workstation

Aucune image, aucun CSV individuel, aucun poids n'est versionné dans HOVIS. Tout ce qui suit a été exécuté **localement**, hors du dépôt, dans `ARGOS_MLOPS_LOCAL/sci-03/`. Aucune opération distante n'a modifié quoi que ce soit : ni lancement, ni transfert, ni création de job.

## 1. Récupération sélective (sans fusion de `integration`)
- **Source :** `origin/integration` au commit `77dc1af23a0cee15c55fdff1735a8c3c0e4d4570`, extraite par `git archive`. Seuls ces chemins ont été pris :
  - `data/raw/workstation` ;
  - `data/processed/workstation` ;
  - `data/models/workstation/yolo26n.pt`.
- **Résultat :** 100 fichiers dans `ARGOS_MLOPS_LOCAL/sci-03/integration-77dc1af/`.
- **Poids `yolo26n.pt` (Git LFS) :** 5 544 453 octets, SHA-256 `9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef`. Les deux valeurs sont **conformes**.

## 2. Contenu réel et provenance
| Section (config du groupe) | Jeu | Images | Assets | Provenance déclarée par le groupe |
|---|---|---|---|---|
| `press_cell` | `poste_5s_11` | 5 good + 5 anomaly | reference, labels.csv, README | synthétique (planche générée, labels = intentions) |
| `machine_cell` | `poste_bleu_5s_11` | 5 + 5 | reference, labels.csv, README | synthétique (planche générative, labels provisoires) |
| `machine_cell_variant` | `poste_variante_5s_11` | 5 + 5 | reference, labels.csv, README | synthétique (planche découpée, étiquettes indicatives) |
| `electrical_bench` | `poste_electrique_5s_11` | 5 + 5 | reference, labels.csv | pas de README ; la config du poste dit « synthetic pilot » |

Les quatre manifestes déclarent donc `synthetic: true` et `image_provenance: synthetic`. Ce **ne sont pas** des données industrielles : les README du groupe disent « ne pas utiliser comme benchmark industriel indépendant ».

Les colonnes de `labels.csv` diffèrent d'un jeu à l'autre. Elles correspondent exactement au champ `labels:` de chaque `stations/<section>.yaml`.

## 3. Préparation : `mlops/datasets_prep/workstation_group.py`
- **Chemins relatifs du groupe acceptés :** `good/good_01.png` et `anomaly/anomaly_01.png` sont acceptés et leur arborescence est conservée.
- **Chemins refusés :** chemin absolu, lecteur (`C:`), `\`, segment `.` ou `..`, et tout chemin qui sortirait du dossier.
- **Assets versionnés, avec leur SHA-256 :** image de référence, `labels.csv`, `README.txt`. Chaque copie est vérifiée.
```powershell
$py = 'C:\Users\GDYZ5751\ARGOS_MLOPS_LOCAL\.venv\Scripts\python.exe'
$s  = 'C:\Users\GDYZ5751\ARGOS_MLOPS_LOCAL\sci-03'
& $py -m mlops.datasets_prep.workstation_group --source-root "$s\integration-77dc1af\data\raw\workstation" --output-root "$s\staged"
```

## 4. Évaluations scientifiques originales (locales)
- **Commande :** celle du groupe, sans aucune modification de code, de seuil, d'hyperparamètre ni d'algorithme : `python -m usecases.workstation.evaluate --station <section> --data-root data --annotate`.
- **Environnement :** les versions figées de `pipeline.yaml` (ultralytics 8.4.219, torch 2.5.1 CPU, opencv 4.11.0.86, numpy 1.26.4).

| Section | Anomalies signalées | Bonne raison | Fausses alertes | Latence moyenne |
|---|---|---|---|---|
| press_cell | 5/5 | 5/5 | 0/5 | 528 ms |
| machine_cell | 4/5 (`missing_object` manquée) | 4/5 | 0/5 | 447 ms |
| machine_cell_variant | 5/5 | 5/5 | 0/5 | 495 ms |
| electrical_bench | 5/5 | 5/5 | 0/5 | 447 ms |
| **Total** | **19/20** | **19/20** | **0/20** | |

**Comparaison avec les CSV du groupe, image par image (40 images) :**
- décisions, exactitude, « bonne raison », objets trouvés et échecs d'alignement sont **identiques** ;
- seuls 3 scores diffèrent, d'au plus 0,01, sans effet sur les décisions (`press_cell/anomaly_01`, `electrical_bench/anomaly_01` et `anomaly_03`).

**À savoir :** l'évaluateur résout le chemin du poids par rapport à la racine du dépôt. Faute de fichier à cet endroit, Ultralytics a téléchargé le `yolo26n.pt` officiel. Ce fichier est **identique** au poids LFS (même SHA-256) et a été supprimé du dépôt ensuite.

## 5. Analyseur réel côté RUN
`ZoneWorkstationAnalyzer` a été chargé par le registre de la plateforme, à partir d'une **copie temporaire** des `config.yaml`. Le fichier versionné reste sur l'analyseur factice.
- Les trois cas d'usage se chargent ; le contrat est respecté. Le pire temps d'`analyze()` est de 280 ms pour Workstation, sous la limite de 2 s.
- Les images réelles de `press_cell` donnent les scores attendus : 0,0 pour la photo conforme, 1,0 pour un objet ou une personne sur le tapis bleu.
- **Activation permanente :** placer `data/raw/workstation` et `data/models/workstation/yolo26n.pt` dans le dossier `data/` (ignoré par Git) du poste RUN, puis passer `analyzer_class` à `usecases.workstation.model:ZoneWorkstationAnalyzer`.

## 6. Une section, un modèle
Les quatre sections ont des références, des zones et une normalité apprise différentes : elles ne sont **pas interchangeables**. Le modèle partagé `workstation_industrial` est remplacé par un modèle enregistré **par section** :
- `workspace.argos_poc.workstation_press_cell` ;
- `workspace.argos_poc.workstation_machine_cell` ;
- `workspace.argos_poc.workstation_machine_cell_variant` ;
- `workspace.argos_poc.workstation_electrical_bench`.

Chacun est un modèle géré distinct, avec ses propres versions et ses propres alias `champion`. Un modèle d'une section ne peut donc jamais être comparé à celui d'une autre section, ni promu à sa place. Aucune version Workstation n'existait encore : il n'y a rien à migrer.

## 7. Préparations distantes (essais à blanc)
- **Publications :** les quatre sont OK. Contrôles locaux OK ; familles et versions `group-v1` absentes du volume ; rien n'a été transféré.
- **Job `hovis-workstation-training` :** absent. Les **poids `yolo26n.pt` sont absents du volume**.
- **Fichiers de code :** 36 fichiers à envoyer. Le runner a aussi besoin de `visionhub` et du runner Quality, désormais déclarés dans `job.code_extra`. `pydantic-settings` a été ajouté à l'environnement figé (requis par `visionhub.config`).

## 8. Commandes distantes (chaque étape exige votre autorisation)
```powershell
Set-Location C:\Users\GDYZ5751\Desktop\HOVIS_UNIFIED
$py = 'C:\Users\GDYZ5751\ARGOS_MLOPS_LOCAL\.venv\Scripts\python.exe'
$st = 'C:\Users\GDYZ5751\ARGOS_MLOPS_LOCAL\sci-03\staged'
# 1. Publication des quatre sections (images synthétiques du groupe + assets)
$env:HOVIS_INDUSTRIAL_TRANSFER = '1'
foreach ($f in 'poste-5s-11','poste-bleu-5s-11','poste-variante-5s-11','poste-electrique-5s-11') {
  & $py -m mlops.datasets_prep.publish_industrial --prepared "$st\$f\group-v1" --execute --confirm "$f/group-v1" --family-name "Poste 5S $f"
}
# 2. Envoi du poids vérifié (SHA-256 9b09cc8b...) dans runs/hovis/weights/yolo26n.pt du Volume
#    (par exemple : databricks fs cp <yolo26n.pt> dbfs:/Volumes/workspace/argos_poc/images/runs/hovis/weights/yolo26n.pt)
# 3. Installation du job (copie du job éprouvé, aucun lancement)
$env:HOVIS_TRAINING_REMOTE_SETUP = '1'
& $py -m mlops.training.install_job --pipeline workstation-industrial --execute --confirm hovis-workstation-training
# 4. Lancement : uniquement depuis Training Factory (TrainingService.launch), passerelle démarrée avec
#    scripts\start_hovis_unified.ps1 -EnableRemoteTraining ; choisir la section ET sa famille.
```
