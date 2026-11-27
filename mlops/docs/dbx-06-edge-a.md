# DBX-06-EDGE-A — Package Builder et contrat de raccordement

État au 27 novembre 2026. Ce chantier prépare des packages **locaux de test** et un
contrat de lecture pour le Core. Il ne télécharge aucun poids distant et ne déclenche
aucun déploiement Edge. Les actions Edge du Deployment Center restent désactivées.

## Ce qui est implémenté

- `DatabricksMetadataSource` lit directement la version numérique UC, son tag
  `argos_approval` et le run associé, sans utiliser un snapshot de cache. Il inventorie
  les noms des artefacts du run et, pour MLflow 3, ceux du logged model référencé par
  `models:/m-…`. Les noms sont préfixés `run/` ou `logged_model/` pour éviter une
  ambiguïté de provenance. L'inventaire ne lit pas les octets des poids.
- `PackageBuilder.inspect()` distingue l'approbation UC réelle d'une décision de test.
  `build()` vérifie l'identité modèle/version/run, l'approbation courante, la présence
  du fichier dans l'inventaire, le hash du manifeste dataset du run, la taille de la
  source, puis passe par le validateur. Le `ModelPackage` complet est fourni par un
  manifeste explicite ; aucun prétraitement, seuil ou nom d'adaptateur n'est déduit.
- `LocalFixtureSource` accepte uniquement des fichiers locaux sous une racine dédiée.
  Les packages qui en résultent portent `test_only`. Le constructeur refuse tout
  `ArtifactSource` prétendant aujourd'hui produire un package distant vérifié : le
  transfert des poids n'est pas autorisé.
- `PackageStore` publie hors dépôt dans un dossier nommé par une empreinte calculée
  sur le manifeste, le SHA de l'artefact et la provenance. Publication par renommage
  après vérification, lecture avec revalidation des octets. `PackageProvider.get()`
  refuse par défaut `test_only`. `find(model, version)` reste une recherche de packages
  locaux, pas un second registre de modèles.
- `validate_delivery.py` n'importe plus de classe depuis le manifeste. Il exige une
  liste explicite d'adaptateurs préinstallés et contrôle chemin, taille, SHA-256,
  runtime, format, device, classes, dataset, seuils et post-traitement. Un hash assure
  l'intégrité face à une altération accidentelle ; il n'authentifie pas l'origine.

Le constructeur ne prouve pas qu'un modèle se charge réellement sur l'Edge. Cette
preuve relève du responsable EDGE-C et de ses tests avec l'adaptateur préinstallé.

## Formats et compatibilité réels

`ModelPackage` autorise les couples `onnxruntime/onnx`, `ultralytics/pt`,
`torch/pt|torchscript` et `opencv/onnx`. Chaque couple doit en plus figurer dans la
politique locale d'adaptateurs autorisés (`analyzer_class`, runtime, formats, devices,
paramètres requis). Aucun adaptateur industriel chargé depuis un package n'est présent
dans ce worktree : les analyseurs `usecases/*` sont synthétiques. La politique des
tests nomme `OnnxAnalyzer` uniquement comme fixture ; elle ne prouve aucune capacité
de déploiement. `joblib` et `MLflow pyfunc` ne figurent pas dans le runtime/format du
contrat partagé. Il faudra convenir avec RUN d'une **évolution additive** du contrat
et d'un adaptateur scikit-learn préinstallé avant de construire ces packages. Aucun
chargement dynamique de code ni installation de dépendance n'est prévu.

Un package d'inférence doit contenir ou déclarer de manière vérifiable : artefact(s),
code d'adaptateur préinstallé, versions de runtime et de dépendances, prétraitement,
post-traitement, ordre et signification des classes, seuils, dataset/version, évaluation
et configuration d'entrée/sortie. Un seul fichier ONNX ou PT ne suffit pas.

## Inventaire et éligibilité des modèles existants

Lectures distantes effectuées en lecture seule ; aucun artefact téléchargé.

| Version | Artefacts observés | Verdict de package Edge |
|---|---|---|
| Quality Demo V3, run `6e1fde325b0341d1abd6abf3b1ad6439` | Run : split counts et rapports de confusion. Logged model `m-5382e3e995b1454a8d1d1131ccd7f7df` : `MLmodel`, `quality_model.py`, environnement, `artifacts/classifier.joblib`, `artifacts/metadata.json`. | **Non éligible** : tag d'approbation absent, runtime pyfunc/joblib non prévu dans le contrat, adaptateur Edge absent, package multi-fichiers non spécifié. |
| Quality Demo V4, run `7a5d09bef4594c8bb19d3739151b9103` | Run : split counts et rapports de confusion. Logged model `m-e99ca68a19ef4fd0be143f83b726f3ed` : `MLmodel`, `quality_model.py`, environnement, `artifacts/classifier.joblib`, `artifacts/metadata.json`. | **Non éligible** : approbation absente et mêmes prérequis de format/adaptateur ; taille, hash et contenu effectif des poids ne sont pas vérifiés. |
| Quality Industrial V1, run `f6fd2e72798f490a8296145efad77f2a` | Run : `training/modele.onnx`, `training/config_qualite702.yaml`, `training/config_qualite702_onnx.yaml`, rapports et métriques. `modele.pt` n'apparaît pas dans l'inventaire du run consulté ; sa localisation et sa provenance restent à confirmer. | **Non éligible** : version UC/approbation non vérifiées depuis l'instance configurée, ONNX non validé Edge (écart maximal de probabilité rapporté 0,0148), adaptateur réel absent ; artefact PT non localisé. |

Pour V3/V4, l'inférence réelle est la chaîne `quality_model.py` : lecture de l'image,
29 caractéristiques de forme, `StandardScaler` puis `LogisticRegression` stockés en
joblib, probabilité NOK et seuil de `metadata.json`. Les paramètres effectifs doivent
être extraits et validés depuis les artefacts autorisés avant packaging. Ne pas charger
un joblib d'origine non authentifiée : sa désérialisation peut exécuter du code.

Pour Industrial V1, l'ONNX exporté et les configurations sont des candidats, mais
l'écart PyTorch/ONNX observé doit être jugé selon le critère métier et testé avec
l'adaptateur Edge, en particulier près des seuils. L'absence de verdict différent
sur 18 images synthétiques ne constitue pas une validation industrielle.

## Contrat `PackageProvider` destiné au Core

Interface locale en lecture seule :

```python
record = provider.get(package_sha256)  # refuse test_only par défaut
records = provider.find(registered_model, numeric_version)
```

`record` donne le chemin du manifeste et de l'artefact ainsi que le modèle, la version,
l'empreinte, l'identité de source et le niveau de confiance. Le Core ne doit remettre
les octets qu'à une machine authentifiée et autorisée pour **son** déploiement. Il doit
vérifier à nouveau le hash transmis et ne jamais exposer les credentials Databricks.
Le hash local représente l'identité du package ; il ne vaut pas signature de source.
Le Core et l'Edge ne sont pas modifiés dans EDGE-A.

## Spécification à transmettre au responsable RUN (EDGE-B/C)

Conserver `ModelRef`, `ModelPackage`, `ModelDeployment`, `StationDeploymentStatus` et
l'outbox existants. Prévoir un contrat additif coordonné, sans modifier ici
`visionhub/integration/edge_events.py` :

| Champ | Sens |
|---|---|
| `group_id`, `deployment_id` | Lot et opération individuelle idempotente. |
| `station_id`, `use_case`, `generation` | Cible ; génération monotone par couple poste/cas d'usage. |
| `registered_model`, `version`, `package_sha256` | Version numérique UC et package immuable souhaités. |
| `desired`, `active` | Références distinctes : une tentative échouée ne change pas `active`. |
| `action` | `deploy`, `redeploy` ou `rollback` explicite. |
| `expires_at`, `result`, `error` | Péremption et résultat par poste, sans succès anticipé. |

Séquence proposée : validation humaine et package prêt → Core écrit une génération
souhaitée par poste/cas d'usage → Edge lit la demande, télécharge dans une zone
temporaire, vérifie taille/hash/compatibilité et teste le chargement → échange la
référence active **entre deux cycles** et conserve l'ancienne → écrit confirmation
dans l'outbox → Core confirme `active` seulement après réception du modèle/version/hash
effectivement actifs avec le bon `deployment_id` et la bonne génération. En cas
d'échec, publier un résultat de tentative distinct ; garder l'ancien modèle actif.
Une confirmation répétée est idempotente ; une génération ancienne ne remplace pas
une génération plus récente. Un lot peut être partiellement réussi. Redéploiement de
la même version et rollback sont de nouvelles opérations identifiées.

Routes à discuter avec RUN, sous `/api/v1` :

- `POST /edge-deployments` : demander un lot avec clé d'idempotence, modèle/version,
  package hash, postes, action, motif et approbation authentifiée ; retour par poste.
- `GET /edge-deployments/{group_id}` : suivi et état individuel, y compris `pending`,
  `preparing`, `active`, `failed`, `expired`, `partial`.
- `GET /stations/{station_id}/desired-models` : demandes courantes par cas d'usage,
  générations et expirations ; polling Edge simple.
- `GET /edge-packages/{digest}/manifest` et `GET /edge-packages/{digest}/artifact` :
  accès limité à la machine concernée, avec vérification du `PackageProvider`.
- L'ingestion `POST /ingest/v1/events` existante véhicule une confirmation additive
  corrélée ; distinguer l'événement de résultat d'essai de `model.status` actif.

Le `ModelStatusPayload` actuel n'a ni `deployment_id`, ni génération, ni erreur de
tentative. `StationDeploymentStatus` n'est pas un journal d'opérations. RUN doit valider
la forme additive des événements et le maintien de l'état actif dans le Core avant
que les routes ci-dessus soient figées.

**Monitoring DBX-07 :** chaque événement d'inférence devrait porter le modèle UC
réellement exécuté, sa version numérique, le hash du package et un `activation_id`
émis à l'échange atomique. Lier cette référence au cycle au moment de l'inférence ;
ne jamais reconstruire l'historique depuis le dernier `model.status`. Cette évolution
du contrat doit être coordonnée avec RUN et Claude.

## Raccordement Deployment Center (EDGE-D)

Préserver `argos-ui/src/pages/ai-leader/IndustrialFleet.tsx`, `Deployment.tsx`,
`FleetWizard.tsx`, `DeploymentDetail.tsx` et le client
`argos-ui/src/api/deployment.ts`. Après livraison RUN, ajouter dans ce client les
routes Core distinctes des routes Serving MLOps ; utiliser le Core comme source unique
des opérations Edge. Le Parc affiche version souhaitée et version active, l'assistant
groupé envoie un `group_id`, le détail affiche chaque poste et sa confirmation, et les
actions redéployer/rollback ciblent une opération explicite. Polling simple du suivi.
Maintenir les boutons désactivés tant que les routes, l'autorisation et le chargement
effectif Edge ne sont pas éprouvés. Aucune modification frontend n'a été faite ici.

## Recette à poursuivre après autorisations séparées

1. Faire approuver en UC deux vraies versions adaptées, avec traçabilité explicite.
2. Autoriser le téléchargement vérifié des artefacts, identifier la source de confiance
   et compléter le contrat pour les modèles pyfunc/joblib multi-fichiers si retenus.
3. Installer et tester les adaptateurs Edge hors cycle, avec versions figées du runtime.
4. Tester sur plusieurs postes locaux : V3 → V4 → redéploiement V4 → rollback V3,
   mauvais hash, modèle incompatible, poste hors ligne, reprise et redémarrage.
5. Déclarer une opération réussie seulement si la version **effectivement active** est
   confirmée par chaque poste ; conserver les résultats partiels.

La recette locale ne vaut pas sécurité réseau industriel. Au-delà de localhost, prévoir
authentification des postes, autorisation par poste/package, TLS, source d'artefacts
authentifiée, droits de fichiers minimaux et audit des accès. Aucun credential
Databricks n'est destiné aux Edge.
