# DBX-07C — Interface Monitoring

Statut : livré en local sur `feat/argos-integration` (aucun push, aucun merge). L'interface ne
consomme que les API Monitoring de DBX-07B (`/api/mlops/monitoring/*`).

La maquette annoncée n'était pas jointe au message : l'interface suit la spécification écrite
et la direction artistique de Datasets / Training Factory. Elle sera ajustée à la maquette.

## 1. Fichiers

| Fichier | Rôle |
|---|---|
| `argos-ui/src/api/monitoring.ts` | Client et types des routes Monitoring. |
| `argos-ui/src/pages/ai-leader/monitoring/MonitoringDashboard.tsx` | En-tête, filtres, 6 KPI, graphiques globaux, catalogue. |
| `argos-ui/src/pages/ai-leader/monitoring/ModelDetail.tsx` | Détail en 7 onglets, chargés à l'ouverture. |
| `argos-ui/src/pages/ai-leader/monitoring/shared.tsx` | Ressources (store DBX-PERF-01, clés `mon:`), libellés, formats. |
| `argos-ui/src/pages/ai-leader/monitoring/charts.tsx` | Barres, barres appariées, séries, barres horizontales (SVG, sans bibliothèque). |
| `argos-ui/src/pages/ai-leader/monitoring/monitoring.css` | Styles propres ; réutilise `training.css` et `ui.css`. |

**Modifications partagées (minimales) :**
- `pages/ai-leader/Monitoring.tsx` : réexporte la nouvelle page (comme `Training.tsx`).
  L'ancien rapport Delta reste utilisé par la Vue d'ensemble.
- `pages/ai-leader/common.tsx` : `monitoring.scoped = false` (une ligne). Aucun modèle n'est
  présélectionné et le sélecteur global n'apparaît plus sur cette section.

Aucun fichier Registry ou Deployment n'est modifié.

## 2. Extensions du backend Monitoring (DBX-07B)

Les modules restent sous `mlops/monitoring/` et `mlops/api/monitoring_routes.py`. Les contrats
partagés ne changent pas.

- **Lien exact pièce → inférence.** Une pièce est reliée à une inférence par
  `prediction.event_id`, l'identifiant de l'événement d'inférence. Les corrections héritent
  ensuite du modèle, de la version et du verdict IA initial de cette pièce. Aucun rapprochement
  par nom.
- **Filtres.** `use_case` est disponible sur `inferences`, `human` et `models`.
  `human` accepte aussi `model_key`, `version`, `start` et `end`.
- **Liste des corrections.** `human.items` (500 au maximum) donne le poste, le modèle, la
  version, le verdict IA initial, le verdict précédent, le verdict corrigé, le motif et
  l'inspection physique.
- **Catalogue (`models`).** Chaque ligne indique :
  - la source : `operational` ou `registry` ;
  - le nom et le cas d'usage ;
  - le volume de pièces, la latence P95 et la dernière activité ;
  - les corrections ;
  - l'état de dérive de la dernière version observée, calculé sans écriture :
    `reference_absent`, `insufficient_*`, `incompatible`, `mixed_data`, `stable`, `watch`,
    `alert` ou `no_production_data` ;
  - `needs_investigation`.
- **Dérive.** La réponse inclut aussi :
  - les seuils configurés (`thresholds`) ;
  - les histogrammes de la référence et de la population, sur les mêmes bords ;
  - la représentativité de la référence et ses avertissements.
- **Résumé.** `latency_p95` est ajouté.

Nouveaux tests : lien exact par identifiant d'événement, séparation registre / opérationnel,
états de dérive du catalogue, catalogue en lecture seule, seuils et histogrammes. Au total,
33 tests Monitoring.

## 3. Comportements garantis par l'interface

- **Données simulées.** Pas de mélange avec le réel : l'origine se choisit entre réelle et
  simulée, sans option « tout ». Par défaut, l'origine est la production réelle si elle existe,
  sinon la simulation, signalée par un bandeau et des puces.
- **Six KPI**, chacun avec son périmètre, sa période et son état de disponibilité :
  - modèles surveillés ;
  - postes concernés ;
  - inférences ;
  - latence P95 ;
  - alertes de dérive ;
  - modèles à investiguer.
- **Aucune série inventée.** Les courbes viennent des instantanés journaliers des collectes
  explicites. Une série d'un seul point s'affiche comme un point avec son résumé. Les P50 / P95
  de plusieurs modèles ne sont jamais combinés : on affiche alors un tableau par modèle.
- **Absence d'alerte, référence absente et effectif insuffisant** sont trois états distincts,
  avec un libellé et une explication pour chacun.
- **Modèles non associés.** `argos-demo-quality` est présenté comme « Opérationnel · non associé
  à Unity Catalog ». Il n'est jamais assimilé à quality_demo ou quality_industrial.
- **Performances.** Elles portent la mention « évaluation hors ligne, pas une mesure de
  production » et indiquent le dataset, sa version, le split `test`, la taille et la
  représentativité. Un test de 18 images est marqué non représentatif. Seules les versions
  évaluées sur le même split sont comparées.
- **Figer une référence** est une action explicite : formulaire, confirmation, puis validation
  par le backend (refus 409 affiché).
- **Corrections humaines.** Le taux d'accord reste indisponible, avec sa raison. Les pièces non
  corrigées ne sont jamais présentées comme confirmées.
- **Écritures.** La page n'écrit rien à son chargement. « Collecter maintenant » demande une
  confirmation. Les signaux de réentraînement sont en lecture seule (aucune action, DBX-08).
- **Fraîcheur et erreurs** :
  - la date de lecture du Core est affichée ;
  - une agrégation partielle (troncature) déclenche un bandeau ;
  - chaque bloc a sa propre erreur ;
  - le dernier résultat connu est conservé (store DBX-PERF-01).

## 4. Recette

- URL : `http://127.0.0.1:5174/ai-leader?section=monitoring`, avec le profil AI Leader.
  La passerelle tourne sur le port 8020, sans le verrou `HOVIS_TRAINING_REMOTE`.
- Données actuelles, toutes simulées :
  - 91 inférences, 3 modèles opérationnels et 2 modèles du registre sans inférence ;
  - argos-demo-quality : « Référence insuffisante » (87 < 100), 1 correction NOK→OK reliée
    exactement ;
  - safety et workstation : « Référence absente » ;
  - production réelle : 0 inférence.
- La capture d'écran automatique n'a pas pu être faite : la politique du poste interdit le
  débogage à distance d'Edge. La vérification visuelle reste à faire par l'équipe.
