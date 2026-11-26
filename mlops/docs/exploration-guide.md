# MLOPS-01 — Parcours d'exploration manuel

À suivre dans l'ordre, dans un terminal PowerShell ouvert à la racine du dépôt (`hackathon-hutchinson`). Chaque étape indique **ce qu'il faut observer** et **pourquoi c'est important**. Concepts : [foundation.md](foundation.md).

Les identifiants ci-dessous sont ceux de la démo générée le 2026-11-26. Ils seront différents si vous relancez `seed_demo.py --force` ou sur une autre machine : prenez alors ceux affichés par vos commandes.

```powershell
$mlops = "$env:USERPROFILE\ARGOS_MLOPS_LOCAL"
$py = "$mlops\.venv\Scripts\python.exe"
$env:MLFLOW_DISABLE_AGENT_HINT = "1"
$RUN = "15c4163c004a4c33a13c6e3453ceeee7"      # random-forest-c (champion)
$RUN2 = "ac48ccfa5e4b410590f5f3a9489b419b"     # gradient-boosting-d (challenger)
```

## 0. Démarrer et vérifier le serveur

```powershell
powershell -ExecutionPolicy Bypass -File mlops\scripts\start_mlflow.ps1
powershell -ExecutionPolicy Bypass -File mlops\scripts\check_mlflow.ps1
```

**Observer** : 9 lignes `[OK]`, dont `Localhost only` (`127.0.0.1`) et `Python SDK -> server`. **Pourquoi** : on prouve séparément le réseau (non exposé), le HTTP, l'UI, l'API REST, le SDK et les deux stores.

## 1. Ouvrir MLflow UI

Navigateur : **http://127.0.0.1:5000**.

**Observer** : trois expériences, `Default`, `argos-foundation-demo` (4 runs réels) et `argos-foundation-demo-simulated-curves` (1 run **simulé**). **Pourquoi** : la courbe simulée est volontairement isolée pour ne jamais être confondue avec un résultat d'entraînement.

## 2. Explorer l'expérience et comparer les runs

UI : `argos-foundation-demo` → cocher les 4 runs → **Compare**.

**Observer** :
- les paramètres qui diffèrent (`architecture`, `hp_*`) et ceux qui sont communs (`dataset_*`, `split_*`, `seed`) ;
- `val_f1_macro` : `random-forest-c` 0,8113 > `gradient-boosting-d` 0,8062 > `random-forest-b` 0,7909 > `sgd-logistic-a` 0,5655 ;
- seuls les deux runs retenus ont des métriques `test_*`, et le tag `argos.test_evaluated_after_selection=true`.

**Pourquoi** : la sélection se fait **sur la validation**. Le test n'est calculé qu'après coup, pour les deux modèles choisis, afin de mesurer sans biais. C'est la règle à respecter plus tard avec les vrais modèles.

## 3. Paramètres, tags et dataset inputs d'un run

UI : ouvrir `random-forest-c` → onglets **Overview** et **Parameters**, encart **Datasets**, **Tags**.

```powershell
& $py -m mlops.scripts.inspect_mlflow params $RUN
```

**Observer** :
- `hp_n_estimators=300`, `split_train_size=1800`, `split_validation_size=600` ;
- les tags `synthetic=true`, `argos.git_commit` et `argos.git_dirty` ;
- les datasets `…-train` (contexte `training`), `…-validation` et `…-test`, chacun avec son **digest**.

**Pourquoi** : c'est la **traçabilité**. On sait avec quelles données, quel code et quelle configuration ce modèle a été produit.

## 4. Métriques et historique

UI : onglet **Model metrics**, ouvrir `history_val_accuracy` (axe X = *Step*).

```powershell
& $py -m mlops.scripts.inspect_mlflow metrics $RUN
& $py -m mlops.scripts.inspect_mlflow history $RUN history_val_accuracy
& $py -m mlops.scripts.inspect_mlflow history $RUN2 history_val_log_loss
```

**Observer** :
- pour la forêt, step = nombre d'arbres (30 → 300) : 10 points réels ;
- pour le boosting, 150 étapes réelles (`staged_predict_proba`) ;
- les métriques par classe : `val_precision_class_0`, `val_recall_class_0`…

**Pourquoi** : une *metric* est la dernière valeur, l'*historique* est la série complète par `step`. Comparez avec `simulated_loss` de l'expérience simulée : même mécanisme `log_metric(step=…)`, mais des valeurs calculées par une formule.

## 5. Artefacts : UI, téléchargement, disque

UI : onglet **Artifacts** du run → `reports/confusion_matrix.png`.

```powershell
& $py -m mlops.scripts.inspect_mlflow artifacts $RUN
& $py -m mlops.scripts.inspect_mlflow artifacts $RUN reports
& $py -m mlops.scripts.inspect_mlflow download $RUN reports/confusion_matrix.png
explorer "$mlops\downloads\$RUN"
Get-ChildItem -Recurse "$mlops\storage\mlartifacts\1\$RUN"
Get-ChildItem "$mlops\storage\mlartifacts\1\models"
```

**Observer** :
- le même fichier est visible à trois endroits : dans l'UI, dans `downloads\` (copie obtenue **par HTTP**) et dans `mlartifacts\` (stockage du serveur) ;
- le modèle n'est **pas** dans le dossier du run mais dans `models\m-…\artifacts\` (`MLmodel`, `model.skops`, `input_example.json`, `requirements.txt`).

**Pourquoi** : en industriel, `mlartifacts` sera un stockage objet distant. Le client ne fait que des appels HTTP, donc rien ne change côté code.

## 6. Model Registry, versions et alias

UI : menu **Models** → `argos-foundation-demo-model`.

```powershell
& $py -m mlops.scripts.inspect_mlflow models
& $py -m mlops.scripts.inspect_mlflow versions argos-foundation-demo-model
& $py -m mlops.scripts.inspect_mlflow resolve models:/argos-foundation-demo-model/1
& $py -m mlops.scripts.inspect_mlflow resolve models:/argos-foundation-demo-model@champion
```

**Observer** :
- v1 a `aliases=["champion"]`, `run_id=15c4…` et `model_id=m-676a…` ; v2 a `challenger` ;
- `resolve` renvoie aussi `argos_model_ref`, le contrat ARGOS `ModelRef`.

**Pourquoi** : `…/1` désigne une version **figée**, `…@champion` désigne **ce qui est champion maintenant**. Le connecteur traduit la réponse dans le langage d'ARGOS.

## 7. Déplacer un alias (promotion dans le Registry, pas un déploiement)

```powershell
& $py -m mlops.scripts.inspect_mlflow set-alias argos-foundation-demo-model champion 2
& $py -m mlops.scripts.predict_registered                      # -> version 2
& $py -m mlops.scripts.inspect_mlflow set-alias argos-foundation-demo-model champion 1
& $py -m mlops.scripts.predict_registered                      # -> version 1
& $py -m mlops.scripts.predict_registered --model-uri models:/argos-foundation-demo-model/2
```

**Observer** : la même URI `@champion` charge un autre modèle après le déplacement. L'URI numérique, elle, ne change jamais. **Pourquoi** : c'est le mécanisme moderne de promotion, qui remplace les anciens *stages* dépréciés. Aucun poste Edge n'est concerné : charger un modèle n'est pas le déployer.

Essayez aussi une opération refusée par le connecteur :

```powershell
& $py -m mlops.scripts.inspect_mlflow set-alias argos-quality champion 1   # ForbiddenOperationError
```

## 8. Inspecter SQLite en lecture seule

```powershell
& $py -m mlops.scripts.inspect_sqlite
```

**Observer** :
- environ 70 tables, des centaines de lignes dans `metrics` (un point d'historique par ligne) ;
- `model_versions` avec les colonnes `run_id` et `source` ;
- `registered_model_aliases` qui associe chaque alias à sa version.

**Pourquoi** : comprendre où vivent les métadonnées. La base est ouverte en `mode=ro`. Le code ARGOS ne fait **jamais** cela : le schéma est interne à MLflow et change entre versions.

## 9. Interroger le serveur via le connecteur (Python interactif)

```powershell
& $py
```

```python
from mlops.connectors import ArgosMlflowConnector, RunNotFoundError
c = ArgosMlflowConnector()
c.ping()
[e.name for e in c.list_experiments()]
best = c.list_runs("argos-foundation-demo", order_by=["metrics.val_f1_macro DESC"])[0]
best.run_name, best.metrics["val_f1_macro"]
v = c.resolve("models:/argos-foundation-demo-model@champion")
c.to_model_ref(v, "champion").model_dump()
try:
    c.get_run("0" * 32)
except RunNotFoundError as e:
    print("erreur explicite :", e)
```

**Pourquoi** : ce sont exactement les appels que fera le futur backend FastAPI pour l'écran AI Leader.

## 10. Persistance

```powershell
powershell -ExecutionPolicy Bypass -File mlops\scripts\stop_mlflow.ps1
& $py -m mlops.scripts.inspect_mlflow ping        # ServerUnavailableError (code 2)
powershell -ExecutionPolicy Bypass -File mlops\scripts\start_mlflow.ps1
& $py -m mlops.scripts.inspect_mlflow versions argos-foundation-demo-model
```

**Observer** : pendant l'arrêt, une erreur claire. Après le redémarrage, les mêmes versions et alias. **Pourquoi** : tout l'état est dans `storage\`, pas dans la mémoire du serveur.

## 11. Tests

```powershell
& $py -m pytest mlops/tests -v                               # 17 unitaires (6 intégration ignorés)
$env:ARGOS_MLFLOW_IT = "1"; & $py -m pytest mlops/tests -v   # 23 tests contre le serveur réel
Remove-Item Env:ARGOS_MLFLOW_IT
```

## Où regarder en cas de problème

| Symptôme | Où regarder |
|---|---|
| Le serveur ne démarre pas | `$mlops\logs\mlflow-server.err.log` |
| Port 5000 occupé | `start_mlflow.ps1 -Port 5001`, puis `$env:MLFLOW_TRACKING_URI = "http://127.0.0.1:5001"` |
| `UnicodeEncodeError` dans un script personnel | appeler `mlops.config.utf8_console()` (MLflow affiche des emoji) |
| `Untrusted types` au log d'un modèle d'arbres | `skops_trusted_types=["sklearn.tree._tree.Tree"]`, à réserver aux modèles que vous venez d'entraîner |
