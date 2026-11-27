# DBX-06-FINAL — Parc industriel et préparation DBX-06-EDGE

## État raccordé

Le Centre de déploiement ouvre **Parc industriel**. Les onglets **Databricks Serving** et
**Historique** conservent les fonctions DBX-06B/C. La liste des postes lit
`GET /api/v1/stations`. Un détail sélectionné lit `GET /api/v1/stations/{id}` et
`GET /api/v1/stations/{id}/model-status`. Cette dernière route conserve le nom et la version
locale, même si `StationSummary.models` ne peut pas créer un `ModelRef` pour une version
non numérique. Les appels de détail sont à la demande ; le tableau filtre, trie et pagine
les stations reçues, par pages de 20. Le Core ne fournit pas de pagination serveur.

Les KPI de connexion et de postes portent sur les stations réellement retournées par le Core.
Le compteur de modèles chargés compte les statuts `loaded` signalés par des postes
**non simulés et en ligne**, y compris si la version locale n'est pas numérique.
Une station simulée reste visible et étiquetée, mais son
modèle ne devient pas un modèle industriel réel. `online` est une estimation Core fondée sur
la dernière communication. La version souhaitée, les écarts de version et les opérations
Edge en cours ne sont pas exposés : leurs KPI affichent **Indisponible**. Un modèle chargé
n'est jamais déclaré « à jour » par comparaison avec l'alias champion.

Le tableau présente trois cas d'usage et les filtres vérifiables depuis `StationSummary`.
Le filtre d'écarts est présent, désactivé avec sa cause. Le panneau de détail affiche les
faits `model.status` et des actions distinctes Déployer, Redéployer et Rollback, désactivées.
L'assistant de sélection multiple prépare le parcours complet, mais sa confirmation est
désactivée : aucun contrôle de compatibilité, package ni retour individuel n'existe encore.
Il ne lance aucune mutation.

Le Registry conserve son catalogue unique. Son bouton **Ouvrir** est explicite, tâche et
architecture sont affichées séparément si les tags UC existent, et l'état d'approbation
est associé à la version sélectionnée. Les graphiques de comparaison ne sont affichés
que lorsque dataset, protocole et découpage sont déclarés comparables. Une version sans
décision est distinguée d'un dernier candidat sans alias.

## Pourquoi le parc de cette recette est vide

Sur l'instance isolée `127.0.0.1:8024`, `GET /api/v1/stations` retourne `[]` : la base
`ARGOS_CORE_DB` de cette prévisualisation ne contient aucun événement de station. Le
frontend n'ajoute aucun poste fictif. `GET /api/mlops/models` ne retourne actuellement
que `quality-poc` dans cette instance ; `quality_industrial` ne peut apparaître que lorsque
la famille est déclarée dans la configuration gérée par `ARGOS_DBX_MODELS_FILE` et que
la passerelle est relancée par son responsable. Le frontend ne contient aucun ID de modèle
codé en dur ; le test de catalogue vérifie une nouvelle famille `quality_industrial`.

Pour une recette industrielle indépendante, démarrer **une nouvelle** passerelle avec
`ARGOS_CORE_DB` pointant vers une base de démonstration dédiée, puis alimenter cette même
passerelle par les événements Edge/SIM-01 via `POST /ingest/v1/events`. Démarrer un nouveau
Vite avec `ARGOS_API_TARGET` pointant vers cette passerelle. Dans une application intégrée,
les routes `/api/v1/*` doivent pointer vers le Core réellement alimenté. Ne pas copier une
base active pendant des écritures, et ne pas faire pointer la prévisualisation vers les
services de Claude sans coordination. Les nouvelles versions de modèles sont découvertes
via `GET /api/mlops/models`, puis leurs statuts UC : l'ajout de la famille dans la
configuration MLOps relève du responsable de l'intégration.

Recette actuelle :

```powershell
Invoke-RestMethod 'http://127.0.0.1:8024/api/v1/stations'
Invoke-RestMethod 'http://127.0.0.1:8024/api/mlops/models'
```

Ouvrir `http://127.0.0.1:5176/ai-leader?section=deployment` ; l'onglet Parc s'ouvre
par défaut. L'onglet Databricks Serving garde les cibles, l'assistant et le suivi
d'opération existants. L'onglet Historique n'invente aucune opération Edge. Le lancement
isolé et le drapeau `VITE_LIFECYCLE_READ_ONLY=true` figurent dans
[`dbx-06c-ui.md`](dbx-06c-ui.md).

## Plan technique DBX-06-EDGE — à valider avec le responsable RUN industriel

1. **Source et manifeste.** Une version numérique approuvée de `ModelRef` référence une
   version immuable UC/MLflow. Le producteur construit `ModelPackage` avec cas d'usage,
   `analyzer_class`, runtime, prétraitement, classes, seuils, dataset, évaluation et
   `ArtifactRef` (URI, taille, format, SHA-256). Le validateur existant
   `mlops.delivery.validate_delivery` vérifie le manifeste et le fichier local quand
   disponible. Aucun artefact industriel ne passe par Git.
2. **État souhaité.** Après une approbation humaine distincte, le futur Core conserve
   pour chaque poste et cas d'usage la version numérique souhaitée, l'empreinte du
   package, le motif, l'auteur authentifié et un identifiant d'opération idempotent.
   Il faut définir les routes de lecture/commande avec RUN avant tout changement des
   contrats ou du Core. L'alias champion ne modifie pas cet état implicitement.
3. **Distribution.** Un canal autorisé remet un manifeste et un artefact versionnés à
   l'Edge ; l'Edge télécharge en répertoire temporaire, vérifie taille et SHA-256,
   puis valide runtime, dépendances, schéma et compatibilité matérielle avant activation.
   Une erreur laisse la version chargée intacte.
4. **Activation sûre.** L'Edge prépare l'analyseur hors du chemin de production,
   attend une frontière entre deux cycles, échange atomiquement la référence active
   et conserve la version précédente. Il émet un événement `model.status` avec
   `model_name`, `model_version`, `package_sha256`, `loaded` et `error`. L'outbox
   Edge → Core existante assure le rejeu. La réussite d'une demande n'est acquise
   qu'après confirmation individuelle du modèle et de l'empreinte réellement chargés.
5. **Redéploiement et rollback.** Redéployer la même version crée une opération
   distincte avec le même `ModelRef`, sans feindre un changement de version. Un rollback
   explicite cible le package précédent conservé et repasse les mêmes contrôles et
   confirmations. Un lot affiche un résultat par machine et un état global partiel
   si les machines divergent. Une machine hors ligne reste en attente ou en erreur
   selon une politique RUN à définir ; aucun succès anticipé.
6. **Validation.** Tests sur doublures et postes de démonstration isolés : hash erroné,
   incompatibilité runtime, interruption réseau, cycle pendant préparation,
   confirmation perdue puis rejouée, machine hors ligne, réussite partielle,
   redéploiement, rollback, reprise après redémarrage. Pas de transfert de poids
   industriels avant accord spécifique.

**Passage de relais RUN / Claude.** RUN doit confirmer l'API de commande, la politique
d'installation entre cycles, les capacités matérielles et les états hors ligne. Claude
doit confirmer la publication du manifeste/artefact versionné et la déclaration des
nouveaux modèles, dont `quality_industrial`, dans `ARGOS_DBX_MODELS_FILE`. Ce document
est une proposition technique ; aucune de ces interfaces n'a été implémentée ici.
