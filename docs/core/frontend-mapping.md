# Raccordement du frontend ARGOS au Core

Le groupe Frontend conserve les écrans et l'identité visuelle de `argos-ui/` (branche `interface`) et pourra réutiliser les contrats générés de `frontend/`. CORE-01 ne modifie aucune application React. L'API `argos-ui/src/api/client.ts` historique demande des agrégats `/api/*` qui **ne correspondent pas** directement à `/api/v1/*` ; une couche d'adaptation frontend ou un nouveau contrat revu en équipe sera nécessaire.

| Écran / composant `argos-ui` | Données demandées | Endpoint CORE-01 et paramètres | Transformation / limite |
|---|---|---|---|
| `Superviseur.tsx` cockpit et `Cellule.tsx` | Postes, état, cellules, compteurs | `GET /api/v1/stations` → `StationSummary[]`, `GET /api/v1/kpi?from=&to=` → `ProductionKPI` | Grouper les postes par `cell` ; `cell` actuel est seulement le préfixe de l'ID. Objectif global et graphiques par heure indisponibles. |
| `Superviseur.tsx` alertes et actions | Épisodes, sévérité, statut | `GET /api/v1/alerts?status=open&station_id=`, `POST /api/v1/alerts/{id}/acknowledge|validate|reject|resolve` → `Alert` | Mapper les catégories visuelles sur `alert_type`/`use_case`. Maintenance non implémentée ; les règles d'alerte sont des règles de démo. |
| `PosteDetail.tsx` | Statut poste, shift, production, modèle, équipement, historique | `GET /api/v1/stations/{id}` → `StationSummary`, `GET /api/v1/stations/{id}/kpi?from=&to=` → `ProductionKPI`, `GET /api/v1/events?station_id=&limit=`, `GET /api/v1/parts?station_id=&limit=` | Construire la chronologie depuis les événements. Pas de courbe continue ou de capture caméra. `online` est une fraîcheur d'événement, pas un heartbeat. |
| `Operateur.tsx` | Dernière pièce, correction, shift, KPI local | **API Edge**, pas Core : `/production/parts`, `/corrections`, `/shifts/current`, `/kpi` | Conserver la logique Production Engine ; le Core est une vue centrale différée. Signalement Edge encore absent. |
| `AiLeader.tsx` | Modèles, jobs, entraînement, serving, drift | Aucun endpoint MLOps de CORE-01 | Le raccordement relève du chantier de Claude ; `StationSummary.models` fournit seulement l'état de chargement rapporté par l'Edge. |
| `Admin.tsx` | Utilisateurs, rôles, audit, Databricks | Aucun endpoint de CORE-01 | Toujours simulé ; ne pas traiter le garde de route React comme une autorisation serveur. |

Le client baseline `frontend/src/api/core.ts` correspond déjà à `GET /api/v1/stations`, `GET /api/v1/stations/{id}`, `GET /api/v1/alerts` et `GET /api/v1/operator-reports`. Ses routes MLOps déclarées restent à développer. Son mode `mock` est le comportement par défaut ; pour vérifier le vrai Core, le groupe Frontend devra activer `live` et pointer le proxy Core vers `http://127.0.0.1:8020`.

Les champs `StationSummary`, `Alert`, `OperatorReport` et `ProductionKPI` viennent des modèles Pydantic partagés. Aucun contrat généré ni fixture n'a été édité dans CORE-01. Si les écrans requièrent un nouveau `WorkshopOverview` ou un référentiel poste/cellule, proposer le contrat à l'Intégration avant de modifier les types générés.
