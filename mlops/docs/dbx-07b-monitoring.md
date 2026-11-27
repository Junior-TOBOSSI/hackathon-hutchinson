# DBX-07B — Backend Monitoring (développement local)

Statut : implémenté en local sur `feat/argos-integration`. Aucun job, aucun warehouse, aucune
mutation Databricks, aucun changement du Core ni des contrats partagés. L'interface (DBX-07C)
attend la maquette ; seuls les contrats d'API sont préparés.

## 1. Architecture

```
Core API publique (/api/v1/stations, /events, /parts)   MLflow / UC (lecture)   Training Factory (lecture)
              │  (lecture seule, max 500 éléments/poste)           │                      │
              ▼                                                    ▼                      ▼
     mlops/monitoring/sources.py ──► mlops/monitoring/service.py ◄──────────────────────────
                                          │        ▲
                    stats.py (PSI, KS, χ²)│        │ store.py (SQLite local : agrégats seulement)
                                          ▼        │
                          mlops/api/monitoring_routes.py  →  /api/mlops/monitoring/*, /api/mlops/overview/v2
```

| Module | Rôle |
|---|---|
| `monitoring/stats.py` | Fonctions pures : quantiles, bords de référence, histogramme, PSI (numérique et catégoriel), KS (scipy), χ² (si applicable), niveau. |
| `monitoring/sources.py` | `CoreSource` (API HTTP publique du Core uniquement, détection de troncature) et `DeploymentSource` (DBX-06 de Codex, « indisponible » tant que non intégré : rien n'est dupliqué). |
| `monitoring/store.py` | SQLite `ARGOS_MLOPS_HOME/monitoring.sqlite` : instantanés agrégés, références immuables, alertes dédupliquées, journal des collectes. **Aucune copie des événements du Core.** |
| `monitoring/service.py` | Déduplication, agrégation opérationnelle, retours humains, performance hors ligne MLflow, références, dérive, collecte explicite, résumé, signaux de réentraînement. |
| `api/monitoring_routes.py` | Routes, portée de requête DBX-PERF-01 (cache, budget, en-têtes de fraîcheur). Incluses par `routes.py` (une ligne). |

Règles appliquées :
- les **GET n'écrivent jamais** (ni instantané, ni alerte, ni référence) ; seules les écritures sont
  `POST /references` et `POST /collect`, toutes locales. Seule exception technique : à la première
  instanciation, le fichier SQLite est créé avec son schéma vide ;
- inférences dédupliquées par `event_id`, corrections par `correction_id`, pièces par `part_id` ;
- **aucun rapprochement par nom** : une inférence Core porte `model_name = argos-demo-quality`,
  qui n'est pas un modèle UC. Elle reste sous la clé `unassociated:<use_case>:<model_name>` avec
  `registry_link = "not associated with the registry"`. Le lien exact UC demandera une référence
  de paquet (voir §7) ;
- simulé et réel jamais mélangés en silence : filtre `data_kind = real | simulated | all` ; un
  événement est simulé si son drapeau ou son poste l'est ;
- une lecture Core tronquée (500 éléments atteints pour un poste) rend toute agrégation `partial` ;
- humain : une pièce non corrigée **n'est pas** une prédiction confirmée ; sans confirmations
  enregistrées, le dénominateur est inconnu → `agreement_rate = null`.

## 2. Routes

Toutes sous `/api`. Paramètre commun `fresh=true` (contourne le cache Databricks) ; en-têtes
`x-hovis-fetched-at` / `x-hovis-cache` sur les lectures Databricks.

| Méthode | Route | Contenu |
|---|---|---|
| GET | `/mlops/monitoring/summary?data_kind=` | statut, sources, modèles suivis, postes, inférences, pièces, alertes ouvertes, dernière collecte, `simulated_only` |
| GET | `/mlops/monitoring/models?data_kind=` | une ligne par clé (`registry:<id>` ou `unassociated:…`) : versions, postes, volume, alertes, références |
| GET | `/mlops/monitoring/models/{model_key}` | détail : opérationnel, références, alertes |
| GET | `/mlops/monitoring/inferences?data_kind=&station=&model_key=&version=&start=&end=` | agrégats par modèle / version / poste et fenêtre : volume, cadence/h, histogramme des scores (20 classes), décisions, latences moyenne/p50/p95, première/dernière activité ; erreurs observées sur les pièces ; état des runtimes |
| GET | `/mlops/monitoring/human?data_kind=&station=` | pièces corrigées, corrections, types, faux rejets / défauts manqués **observés**, inspections physiques, `verified_parts = null`, `agreement_rate = null` |
| GET | `/mlops/monitoring/performance/{model_id}` | métriques hors ligne MLflow par version (test), par classe, matrice de confusion, empreinte du split de test, groupes comparables, représentativité |
| GET | `/mlops/monitoring/drift?model_key=&version=&data_kind=&reference_id=&start=&end=` | dérive calculée à la demande contre une référence stockée (n'écrit rien) |
| GET | `/mlops/monitoring/alerts?state=open\|resolved` | alertes MLOps (distinctes des alertes Supervisor) |
| GET | `/mlops/monitoring/history?scope_key=&data_kind=` | instantanés journaliers + journal des collectes |
| GET | `/mlops/monitoring/references?model_key=` | références figées (sans les observations brutes) |
| POST | `/mlops/monitoring/references` | fige une référence immuable : `{"source":"offline_test","model_id","version"}` ou `{"source":"operational_window","model_key","version","start","end","data_kind":"real\|simulated"}` ; 409 si elle existe déjà |
| POST | `/mlops/monitoring/collect` | collecte explicite et idempotente (aucun planificateur) |
| GET | `/mlops/monitoring/retraining-signals/{model_id}` | signaux DBX-08 en lecture seule ; `action = none` |
| GET | `/mlops/overview/v2` | blocs `datasets`, `training`, `registry`, `deployment` (optionnel), `monitoring`, `stations`, chacun avec `status`, `fetched_at` et `detail` ; un bloc en échec ne masque pas les autres |

Vocabulaire de statut : `available`, `unavailable`, `partial`, `simulated` (blocs) ;
`reference_absent`, `insufficient_reference`, `insufficient_current`, `incompatible`, `available`
(dérive) ; `representative: true | false | null` (références et évaluations hors ligne). La
péremption (`stale`) est portée par les en-têtes DBX-PERF-01 quand Databricks est injoignable.

DTO : dictionnaires propres au monitoring (ci-dessus). `MonitoringMetrics` et les autres contrats
partagés ne sont pas modifiés.

## 3. Statistiques (conventions)

- **PSI** : bords = quantiles de la référence (10 classes, doublons retirés), bords extérieurs
  ouverts (−∞ / +∞, stockés `null` en JSON), mêmes bords appliqués à la population ; classes vides
  lissées à `EPSILON = 1e-4`. Seuils heuristiques configurables : < 0,1 stable, 0,1–0,2 à
  surveiller, ≥ 0,2 alerte. Ce n'est pas un test statistique.
- **KS** : `scipy.stats.ks_2samp` sur les observations brutes (p-valeur choisie par scipy).
- **PSI catégoriel** sur les taux de décision ; **χ²** d'homogénéité seulement si tous les
  effectifs attendus ≥ 5 (sinon `applicable: false` avec la raison).
- **Latence** : écart relatif de moyenne, alerte à +50 %.
- Minimum **100** observations pour la référence et pour la population (sinon pas d'alerte).
- Compatibilité exigée : même clé de modèle et version, même définition de score, même nature
  (synthétique/simulé vs réel). Sinon `incompatible` avec les raisons.
- La dérive mesurée est une dérive **des données / des scores**, jamais une preuve de dérive de
  concept.

## 4. Références, historique, alertes

- Référence = test hors ligne d'une version (`evaluation/predictions.csv`, `score_nok`,
  décisions OK / A_VERIFIER / NOK ramenées à conforme / a_verifier / anomalie) ou fenêtre
  opérationnelle figée (réelle **ou** simulée, jamais les deux). Identifiant déterministe
  (source, modèle, version, run, fenêtre) : un second gel identique est refusé.
- Collecte : recalcule les instantanés journaliers de chaque (clé, version, nature) → les
  événements tardifs sont réconciliés sans doublon. Dérive évaluée sur le **dernier jour observé**
  contre la dernière référence de la même version. Une alerte = une clé
  (modèle | version | portée | nature | indicateur | méthode) : une dérive persistante met à jour
  `last_detected` et garde `first_detected` ; une alerte absente d'une collecte est résolue, sauf
  si le Core est indisponible (absence de données ≠ rétablissement).
- Alertes de disponibilité : runtime de modèle `down` / `degraded` d'un poste.

## 5. Résultats sur les événements simulés existants (Core local, 27/11/2026)

| Mesure | Valeur |
|---|---|
| Postes | 12, tous simulés, 0 en ligne ; aucune troncature (lecture exhaustive) |
| Inférences | 91 (réelles : 0) ; quality 87 (11 postes), safety 3, workstation 1 ; toutes version `1` |
| Décisions | conforme 68, a_verifier 5, anomalie 18 ; score moyen 0,295 |
| Latence | moyenne 15,5 ms, p50 15 ms, p95 19 ms |
| Pièces | 88, dont 1 erreur `CAPTURE_FAILED` |
| Humain | 1 pièce corrigée NOK→OK (faux rejet observé), inspection physique ; taux d'accord : indisponible |
| Clés modèles | 3 `unassociated:*` ; `registry:quality-poc` et `registry:quality-industrial` sans inférence associée |
| Collecte | 3 instantanés (journée du 26/11), relancée : toujours 3 (idempotente) ; 0 alerte |
| Référence hors ligne quality_industrial v1 | 18 images, **non représentative**, synthétique, conforme 6 / anomalie 12 |
| Référence opérationnelle demo-quality (simulée, 26/11) | 87 observations, non représentative |
| Dérive demo-quality | `insufficient_reference` (87 < 100) |
| Dérive référence quality_industrial vs inférences Core | `incompatible` (autre modèle, autre définition de score) |
| Performance quality_demo | v1–v4 sur le même split de test (empreinte identique) → comparables ; v2 champion approuvé, servi |
| Performance quality_industrial v1 | rappel NOK 1,0 ; 0 faux rejet ; latence 12,9 ms ; **test de 18 images, non représentatif** |
| Signaux de réentraînement quality_industrial | non éligible ; 0 nouvelle annotation validée depuis v1 ; 1 correction Core brute (non comptée comme annotation) |
| Overview v2 | datasets, training, registry : available ; deployment : unavailable (DBX-06 non intégré) ; monitoring, stations : simulated |

État protégé inchangé : quality_demo v1 challenger non approuvée, v2 champion approuvée et servie,
v3/v4 candidates ; quality_industrial v1 candidate non approuvée, sans alias.

## 6. Tests

`mlops/tests/test_monitoring.py` (29 tests, fakes, aucun réseau) : PSI (valeur connue, identique,
classes vides, bords ouverts), KS, applicabilité du χ², doublons, troncature (`partial`), source
indisponible (alertes non résolues), séparation simulé/réel, pas de lien par nom, changement de
version dans une fenêtre, agrégats, erreurs des pièces, corrections successives, absence de
dénominateur humain, corrections dupliquées, référence trop petite, population trop petite, scores
incompatibles, synthétique vs réel, dérive mesurée, immutabilité des références, test de 18 images
non représentatif, collecte idempotente avec événement tardif, historique persistant à la
réouverture, alerte persistante non dupliquée puis résolue, GET sans écriture ni appel distant
(warehouse compris). Suite MLOps complète et test de contrat : verts.

## 7. Demande de coordination (Codex — DBX-06-EDGE, et responsable RUN / Core)

1. **Agrégation exhaustive ou pagination** des événements et pièces du Core (`/api/v1/events`,
   `/api/v1/parts` : 500 éléments maximum, sans curseur ni filtre temporel). Proposition :
   `since` / `until` + curseur `after_sequence`, ou un endpoint d'agrégats par fenêtre.
2. **Traçabilité exacte du paquet par inférence** : référence du modèle UC
   (`workspace.argos_poc.<modèle>`), version numérique, SHA-256 du paquet, et horodatage
   d'activation du paquet sur le poste pour associer chaque inférence à une version déployée.
   Sans cela, aucune inférence n'est rattachée au registre.
3. **Événements d'erreur d'inférence** (timeout, modèle non chargé…) indépendants d'une pièce ;
   aujourd'hui seules les erreurs portées par une pièce sont visibles.
4. **Vérifications humaines sans correction** (« confirmé conforme ») pour disposer d'un
   dénominateur et calculer un taux d'accord honnête.
5. **Cellule** renseignée dans `StationSummary.cell` (actuellement `null`) pour agréger par cellule.
6. Côté Deployment (Codex) : exposer les versions désirées par poste pour que `DeploymentSource`
   s'y branche à l'intégration (aucune duplication du service).

## 8. Préparation DBX-07C (interface)

Les routes du §2 sont les contrats proposés pour la refonte de la page Monitoring ; elles
seront ajustées à la maquette. Points d'affichage imposés par le backend : bandeau « simulé »,
statut `partial`, `representative: false`, `agreement_rate` indisponible avec sa raison, et
mention « dérive de données, pas de dérive de concept ».
