# DBX-09 — Page d'accueil AI Leader

**Branche :** `feat/ai-leader-overview`, créée depuis `feat/hovis-unified@1f7159e`.
**Worktree :** `C:\Users\GDYZ5751\Desktop\HOVIS_OVERVIEW`.

Rien n'a été poussé ni fusionné, et Databricks n'a subi aucune mutation.

## 1. Ce qui a été fait
La page d'accueil AI Leader est entièrement refondue selon l'organisation fonctionnelle de la maquette :
- KPI ;
- accès rapides ;
- activité récente ;
- historique des entraînements ;
- état des modèles ;
- infrastructure ;
- Monitoring ;
- réentraînement ;
- datasets.

La charte et la navigation HOVIS sont conservées : logo, navigation horizontale, Jost, marine, rouge signal, fond `#EEF1F6`, cartes blanches, et les composants `Kpi`, `Chip` et `tf-hero`. La maquette n'est reprise ni dans sa charte graphique ni dans sa barre latérale.

## 2. Backend : une seule agrégation
L'agrégation reste unique : l'ancienne implémentation de `/api/mlops/overview/v2`, qui se trouvait dans `monitoring_routes.py`, est **déplacée** dans `mlops/overview/service.py`, sans duplication.

Deux routes :
- `GET /api/mlops/overview/v2` : tous les blocs, ou une sélection avec `?blocks=a,b` ;
- `GET /api/mlops/overview/v2/{bloc}` : un seul bloc, pour un chargement indépendant.

Les sept blocs sont les suivants.

| Bloc | Sources existantes réutilisées | Contenu |
|---|---|---|
| `datasets` | `DatasetStore.catalog()` | Familles, versions publiées, images de la **dernière** version de chaque famille (jamais une somme sur les versions ; total `null` si un compte est inconnu), répartition par cas d'usage |
| `training` | `TrainingService.trainings()`, `kpis()`, `pipelines()` | Runs réels par statut, avec leur date (périmètre : 25 derniers job runs par pipeline) |
| `registry` | `connector.model_status`, journal des décisions Deployment, stations du Core | Par modèle : versions, **candidates** (ni approuvées, ni aliasées, ni rejetées), approuvées, champion, versions **servies par Databricks Serving**, versions **déclarées par les postes (Edge)** — ces deux cibles sont toujours distinctes |
| `infrastructure` | `ping` (mis en cache 30 s), MLflow, Unity Catalog, endpoints, Core, Monitoring | Disponibilité de chaque contrôle, parc (en ligne, hors ligne, simulé), couverture du Monitoring |
| `monitoring` | `MonitoringService.summary` et `models` | Données réelles s'il en existe, sinon **simulées et signalées comme telles** ; inférences, P95, alertes, dérives, références absentes, couverture insuffisante, modèles à investiguer |
| `retraining` | Store DBX-08, état du planificateur, `launch_guard` | Politiques actives et inactives, propositions, conditions satisfaites (dernière évaluation explicite), exécutions automatiques, planificateur, verrou distant |
| `activity` | Les mêmes sources | Événements **réels et datés** avec leur provenance et un lien : dataset publié, lancement et fin d'entraînement, version enregistrée, décision, déploiement, rollback, proposition, alerte |

**Comportement commun à tous les blocs :**
- un bloc ne lève jamais d'exception : il renvoie un statut `available`, `partial` (avec la liste des sources en échec), `unavailable` ou `simulated` ;
- chaque bloc est mis en cache 20 s dans le cache du connecteur (*single-flight*, et *stale-while-revalidate* sur les GET d'INT-GLOBAL-01) ;
- l'API est en **lecture seule** : aucune collecte, aucune évaluation, aucun lancement ;
- rien n'est codé en dur : les nouveaux datasets, modèles, pipelines, postes et politiques apparaissent automatiquement.

**Limite connue :** les **promotions d'alias** ne sont pas datées, car Unity Catalog n'horodate pas les changements d'alias. La page l'indique en toutes lettres.

## 3. Frontend
- `argos-ui/src/api/overview.ts` : client typé.
- `pages/ai-leader/overview/OverviewPage.tsx` et `overview.css` : la page. Elle charge chaque bloc séparément et affiche pour chacun son état de chargement, d'erreur, de données partielles ou simulées, et sa fraîcheur. Le bouton « Actualiser » ne bloque pas l'affichage.
- `pages/ai-leader/overview/history.ts` : logique pure (regroupement par jour ou par semaine, statuts, traduction des motifs), testée par `history.test.ts` avec `node --test`, sans nouvelle dépendance.
- **KPI de première ligne :**
  - familles de datasets (avec versions et images) ;
  - entraînements en cours (avec réussis et échoués) ;
  - versions candidates ;
  - versions approuvées (avec le nombre de champions) ;
  - endpoints Serving prêts ;
  - modèles à investiguer (avec dérives et couverture insuffisante).
- **Accès rapides :** d'abord présents sur la page, ils ont été retirés après revue : le menu latéral couvre les mêmes destinations (§9). L'assistant Nouvel entraînement reste accessible depuis Training Factory.

## 4. Mesures (sonde navigateur Edge headless, 3 passages, même jeu de données)
| Mesure | Avant (ancien accueil, `1f7159e`) | Après |
|---|---|---|
| Premier rendu d'une carte (chargement complet) | 139–296 ms | 173–620 ms |
| Fin des requêtes (chargement complet ; plancher de la sonde : 1,2 s) | 1,21–1,23 s | 1,21–1,24 s |
| Requêtes API par chargement | 9–10 | 8 (7 blocs + `health` de l'en-tête commun) |
| Appels Databricks bloquants | 1 (`health`) | 1 (`health`, pastille de l'en-tête, hors accueil) |
| Retour sur l'accueil depuis un autre module | 155–196 ms | 155–194 ms |
| Bloc API, cache chaud | — | 7–27 ms |

La page affiche beaucoup plus d'informations pour un coût équivalent.

Le premier appel aux blocs pendant le **préchauffage** de démarrage peut prendre 1,4 à 18,8 s (`datasets` : 18,8 s mesurées). Seul le bloc concerné attend ; les autres s'affichent dès qu'ils sont prêts.

## 5. Tests
- **Backend :** `mlops/tests/test_overview.py`, 9 tests :
  - définitions des datasets, modèles et versions ;
  - isolation des blocs : partiel ou indisponible sans bloquer la page ;
  - routes ;
  - données simulées signalées ;
  - infrastructure ;
  - activité datée, triée et liée, avec un lancement distinct de sa fin ;
  - réentraînement en lecture seule.
- **Suite complète :** 386 tests réussis, 11 ignorés (ressources externes). `ruff` propre.
- **Frontend :** `node --test src/pages/ai-leader/overview/history.test.ts`, 5 tests réussis.
- **TypeScript :** propre. Les fichiers `*.test.ts` sont exclus du typecheck applicatif, faute de types Node dans le projet.
- **Builds :** par défaut, et AI Leader réel avec l'industriel live : tous réussis.
- **Recette du rendu réel :** le texte complet de la page a été vérifié. Aucune valeur `undefined`, `NaN` ou `null` ; les données réelles sont affichées.

## 6. Recette
Instance distincte, avec des copies cohérentes (sauvegarde SQLite) des bases de recette unifiées :
```powershell
cd C:\Users\GDYZ5751\Desktop\HOVIS_OVERVIEW
powershell -ExecutionPolicy Bypass -File scripts\start_hovis_unified.ps1 -GatewayPort 8041 -EdgePort 18041 -UiPort 5181 -DataDir C:\Users\GDYZ5751\Desktop\HOVIS_OVERVIEW\var\overview
# arrêt : même commande avec -Stop -DataDir ...\var\overview
```
URL : **http://127.0.0.1:5181/ai-leader**, avec le rôle AI Leader. Le script affiche un avertissement sur le nom de branche : c'est attendu, la branche n'étant pas `feat/hovis-unified`.

## 7. Fichiers partagés modifiés (pour le merge)
| Fichier | Modification |
|---|---|
| `mlops/api/monitoring_routes.py` | `overview/v2` et ses fonctions auxiliaires **retirés** (déplacés dans `mlops/overview/`). |
| `mlops/api/retraining_routes.py` | `SCHEDULER`, une référence en lecture seule vers l'état du planificateur. |
| `mlops/api/routes.py` | Inclusion de `create_overview_router`. |
| `argos-ui/src/pages/ai-leader/Overview.tsx` | Réexport de la nouvelle page. |
| `argos-ui/tsconfig.json` | Exclusion des `*.test.ts`. |

Ni les datasets, ni les pipelines, ni Training Factory, ni les écrans industriels ne sont modifiés.

## 8. Limites
- **Promotions d'alias** non datées (Unity Catalog).
- **Versions Edge :** elles proviennent des `model.status` des postes, sans lien avec le registre tant qu'il n'y a pas de référence exacte de paquet. Aucune n'est déclarée dans la recette simulée.
- **Images :** le compte porte sur la dernière version de chaque famille, pas sur les images uniques entre versions, ce qui demanderait de lire tous les manifestes.
- **Historique des entraînements :** limité aux 25 derniers job runs par pipeline (page de l'API Databricks).
- **Pastille `health` de l'en-tête commun :** elle fait toujours un appel Databricks par chargement (environ 250 ms, non bloquant). Elle est hors du périmètre de l'accueil.

## 9. Revue visuelle : navigation de l'espace AI Leader
Ces changements portent sur le cadre commun `AiLeaderWorkspace.tsx` et le nouveau fichier `workspace.css`. Ils s'appliquent donc à toutes les pages AI Leader ; les écrans industriels ne sont pas concernés.

- **Bandeau allégé :**
  - le sous-titre se réduit à « AI Leader » ;
  - la date de lecture affiche l'heure seule (l'origine « cache serveur » est retirée), mais « dernier résultat connu » est conservé en cas de panne Databricks ;
  - le texte de fraîcheur et le second bouton « Actualiser » sont retirés de l'en-tête de l'accueil.
- **Menu latéral docké** à la place de la barre d'onglets horizontale :
  - une barre fine affiche les « trois traits » à gauche, le nom de la page en cours et, à droite, le sélecteur de modèle, l'heure de lecture et « Actualiser » ;
  - le volet est **ouvert par défaut** et ne se replie ou ne se déplie **que** par les trois traits, sans fermeture au choix d'une page, à Échap ou au clic extérieur. L'état est mémorisé dans `localStorage` (`hovis.aiLeaderMenu`) ;
  - le volet est léger : fond blanc, fine bordure, 216 px ; la page active est sur fond bleu clair avec un liseré rouge. « Politiques » figure en sous-entrée de Training Factory.
- **Vérification :** dans Edge headless (ouverture par défaut, navigation, Échap, clic dans le contenu, bascule, persistance). TypeScript, les tests frontend et le build passent.
