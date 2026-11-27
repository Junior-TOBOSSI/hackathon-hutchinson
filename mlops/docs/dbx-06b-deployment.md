# DBX-06B — cycle de vie Registry et Serving

## Portée

MLflow et Unity Catalog restent la source des versions, tags et alias. Databricks Serving reste
la source de la configuration active. La base SQLite locale conserve seulement les décisions,
les opérations, leurs configurations avant/après, leurs étapes et leurs résultats vérifiés.
L'identité authentifiée est indisponible : `author_declared` et `role_declared` sont des déclarations
de démonstration, jamais une preuve IAM.

Le seul endpoint autorisé pour une mutation Serving dans ce MVP est `argos-quality-poc`. La cible
est déduite des modèles configurés, ce qui permet d'accueillir ultérieurement les candidats de
Training Factory sans créer un second registre. Une opération avec une autre cible est refusée.
L'alias `champion`, l'approbation et la version servie restent indépendants.

## API (passerelle intégrée et serveur MLOps autonome)

Préfixer les chemins suivants par `/api`. Les routes de consultation déjà existantes
(`/mlops/models/{model_id}/status` et `/mlops/models/{model_id}/versions`) restent en place.

| Méthode | Route | Usage |
|---|---|---|
| POST | `/mlops/registry/{model_id}/versions/{version}/decisions` | Décider `approved` ou `rejected` avec motif, auteur et rôle déclarés. Un refus de version servie exige `acknowledge_served_rejection: true` et ne l'arrête pas. |
| GET | `/mlops/registry/{model_id}/versions/{version}/decision-state` | État UC actuel, historique local, version servie et action Serving nécessaire. |
| GET | `/mlops/registry/{model_id}/versions/{version}/decisions` | Historique durable des décisions. |
| POST | `/mlops/deployments/prepare` | Préparer une version **numérique**, vérifier l'approbation, la cible, l'état Serving et enregistrer la configuration actuelle. |
| POST | `/mlops/deployments/{operation_id}/confirm` | Soumettre une seule fois avec le texte `confirmation` exact renvoyé par la préparation (valable 10 min). |
| GET | `/mlops/deployments/{operation_id}` | Réconcilier l'opération par lecture directe de Serving. À interroger périodiquement après confirmation. |
| GET | `/mlops/deployments/{operation_id}/events` | Étapes horodatées. |
| GET | `/mlops/deployments?endpoint=...` | Historique des déploiements et rollbacks. |
| POST | `/mlops/deployments/rollback/prepare` | Nouvelle opération explicite depuis un déploiement vérifié ; confirmation ensuite via la même route. |

La route historique `POST /mlops/models/{model_id}/versions/{version}/approve` garde sa forme et
sa réponse. Elle inscrit désormais une décision motivée `Legacy approval route`, avec auteur
déclaré `unknown`, dans le même journal. Elle ne déplace ni alias ni Serving.

Exemple de préparation (ne pas exécuter contre Databricks sans l'autorisation de recette) :

```json
{
  "model_id": "quality-poc",
  "version": "2",
  "endpoint": "argos-quality-poc",
  "reason": "Evaluation et validation humaines terminées",
  "author_declared": "Nom de démonstration",
  "role_declared": "ai_leader"
}
```

## Sûreté et reprise

Les préconditions et la vérification utilisent le SDK directement, sans repli sur un cache. La
topologie Serving acceptée comporte exactement une entité de modèle custom et, au plus, une route
de trafic à 100 %. La configuration de compute, le scale to zero et la route sont copiés sans
changement ; tout champ non pris en charge bloque la préparation. La version et le numéro de
configuration sont relus juste avant confirmation.

Le journal SQLite (WAL, `synchronous=FULL`) se trouve par défaut sous
`%USERPROFILE%\ARGOS_MLOPS_LOCAL\deployment_operations.sqlite3`. Définir
`HOVIS_DEPLOYMENT_DB` pour un chemin isolé. Une contrainte unique empêche deux opérations actives
sur un endpoint, y compris après redémarrage. Le statut `requesting` est persisté **avant**
l'appel SDK. Une exception ou un timeout après soumission place l'opération en `uncertain` :
consulter `GET /mlops/deployments/{id}` pour confronter l'état distant, sans renvoyer la mutation.
Si la configuration reste ambiguë, une intervention humaine est nécessaire ; aucune relance
automatique n'est effectuée.

Une réponse SDK acceptée ne vaut pas réussite. `succeeded` exige la configuration active demandée,
la version numérique attendue, l'endpoint `READY`, `NOT_UPDATING` et l'entité
`DEPLOYMENT_READY`. Le résultat expose `inference_tested: false` tant qu'aucune inférence n'a été
réalisée. Une mise à jour échouée n'est pas décrite comme un rollback HOVIS. Le rollback est une
nouvelle opération, possible seulement depuis un déploiement vérifié et une version précédente
encore approuvée ; il ne modifie jamais l'alias.

## Recette distante proposée (autorisation distincte requise)

1. Sur une instance isolée, définir `HOVIS_DEPLOYMENT_DB` et relever la configuration active,
   les alias et les versions du registre par des lectures directes.
2. Choisir une version candidate précise. Saisir une décision motivée, puis constater son tag UC,
   l'historique et l'absence de changement d'alias ou de Serving.
3. Préparer un déploiement `argos-quality-poc`. Examiner `previous_config` et `requested_config`,
   notamment compute, scale to zero et trafic, avant toute confirmation.
4. Après **autorisation explicite des écritures distantes**, confirmer, puis interroger l'opération
   jusqu'à un état final. Comparer la version active et les états Serving à la réponse HOVIS.
5. Pour un rollback, vérifier l'approbation de la version précédente, préparer une nouvelle
   opération, comparer les configurations, puis confirmer uniquement si ce retour est autorisé.
6. Tester sur doublure locale les erreurs réseau et les confirmations répétées. Les tests du dépôt
   ne soumettent aucune mutation Databricks.

## Futur déploiement Edge

Serving et les postes industriels sont deux cibles différentes. Le futur chantier RUN réutilisera
`ModelRef`, `ModelPackage`, `ModelDeployment` et `StationDeploymentStatus` déjà définis dans
`visionhub.integration.mlops`. Il devra sélectionner une version numérique et les postes,
distribuer un artefact compatible, vérifier SHA-256, confirmer le chargement local et permettre
un rollback local. Ce chantier n'émet aucun ordre Edge et ne prétend à aucun déploiement de poste.

## Intégration avec Claude

Seuls `mlops/api/platform.py` et `mlops/api/app.py` ont une ligne d'inclusion de route ajoutée.
La route `approve` dans `mlops/api/routes.py` change pour partager l'historique de décisions ;
ces trois fichiers sont des points de conflit potentiels lors de l'intégration de DBX-05.
Les autres nouveaux modules sont dédiés à DBX-06B. Le client TypeScript `argos-ui/src/api/deployment.ts`
est ajouté sans changer les écrans ; les deux maquettes restent attendues.
