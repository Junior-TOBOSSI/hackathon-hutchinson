# INT-GLOBAL-01 — Branche unifiée HOVIS, audit et optimisation

**Branche de référence :** `feat/hovis-unified`.
**Worktree :** `C:\Users\GDYZ5751\Desktop\HOVIS_UNIFIED`.

Aucun push, aucun merge dans `main`. Aucune mutation Databricks.

## 1. Audit Git (27/11/2026)

### Worktrees
| Worktree | Branche | État |
|---|---|---|
| `HACKHATON` | `feat/argos-integration` | Propre. |
| `HOVIS_DEPLOYMENT` | `feat/mlops-unified` | Propre (Codex). |
| `HOVIS_INDUSTRIAL` | `feat/industrial-live` | **2 fichiers modifiés non committés** (`industrial-view.ts`, `demo_shift_app.py`) : travail en cours, non repris et non touché. |
| `HOVIS_DATASETS` | `feat/datasets-catalog` | Propre. |
| `ARGOS_CORE` | `feat/argos-simulator` | Propre. |
| `ARGOS_UI_PREVIEW`, `.kilo/worktrees/glitter-texture` | HEAD détaché | Propres. |

Aucun stash.

### Commits absents de `feat/mlops-unified` (51469d0) et décisions
| Source | Contenu | Décision |
|---|---|---|
| `feat/argos-integration` | 38a09dc, 6dba5f1, 982f214 (DBX-08). | **Mergé.** |
| `feat/industrial-live@3804706` | Écrans live Operator, Supervisor, Cellule et PosteDetail (Core + Edge) ; jauge de shift ; simulateur. | **Mergé**, sans conflit. |
| `feat/argos-simulator@6ffbd35` | Simulateur. | Déjà couvert par `industrial-live` (a598676). |
| `feat/production-engine` | 2 commits marqués « + » par `git cherry`. | Versions antérieures, remplacées par `feat/argos-core`, déjà ancêtre. Non repris. |
| `feat/deployment-center`, `feat/datasets-catalog`, `feat/argos-core`, `feat/dbx-01-integration`, `main` | — | 0 commit manquant. |
| `origin/EPI` (36 commits, `usecases/safety` seulement) | Livraison explicite (`LIVRAISON.md` : « reprendre les fichiers, ne pas fusionner la branche »). | **Fichiers repris** (8cce7c3). Analyseur factice par défaut ; poids hors Git ; patch d'interface non appliqué. |
| `origin/workstation` (13 commits) | Code des quatre sections. | Déjà intégré **sans modification** par INT-DATA-02 (`mlops/pipelines/workstation/kit`, copie de f168032). La branche fait du vrai analyseur l'analyseur **par défaut**, alors que ses données (`raw/workstation/...`) sont absentes. Non repris dans `usecases/workstation`, pour ne pas casser le Production Engine. |
| `origin/quality@394a86a` | Kit `qualite702`. | Déjà intégré (`mlops/pipelines/quality_industrial`). |
| `origin/interface` (3 commits) | Page `TeamLeader` qui **supprime** `Superviseur.tsx` et renomme `Cellule` ; vidéo de pitch (Remotion). | **Isolé** : conflit fonctionnel avec les écrans live d'INT-01. Décision à prendre avec le groupe Interface. La vidéo est hors application. |
| `origin/detection-telephone` | Historique **orphelin** (aucun ancêtre commun), scripts à la racine. | **Isolé** : non intégrable tel quel. La détection de téléphone de la livraison Safety (COCO) couvre l'usage dans la plateforme. |

### Commits de `feat/hovis-unified` (depuis 51469d0)
| SHA | Objet |
|---|---|
| `b5a0c64` | Merge DBX-08. Seul conflit : imports de `mlops/api/routes.py`, résolu en conservant les deux côtés. |
| `772b030` | Merge `industrial-live@3804706`. |
| `8cce7c3` | Livraison Safety (`usecases/safety` depuis EPI `df06ba9`). |
| `24cd2dc` | Correctifs d'intégration (§3). |
| `3d4f2a1`, `a9e3bd9`, `3b2cc89` | Performances, instrumentation et script de démarrage. |
| *(ce document)* | Documentation. |

Les branches sources sont intactes : seules `feat/hovis-unified` et son worktree ont été créés.

## 2. Une seule application
- **Frontend :** `argos-ui` (navigation horizontale, rôles). Les espaces AI Leader et industriel live sont réunis :
  - AI Leader en live : `VITE_LIVE_AI_LEADER=true` ;
  - écrans industriels en live : `VITE_LIVE_INDUSTRIAL=true` ;
  - connexion et administration en démo : `VITE_USE_MOCK=true`.
- **Passerelle :** `mlops.api.platform:app`. Elle regroupe le Core, MLOps, Deployment, Monitoring et Retraining, et vérifie les collisions de routes au démarrage.
- **Edge :** `visionhub.argos_app`, en service séparé (Production Engine, outbox vers le Core).

L'architecture distribuée est conservée.

## 3. Sécurisation (vérifiée sans lancement)
- `TrainingService.launch` reste l'unique chemin de lancement. Toutes les routes suivantes renvoient **403 ou 409** verrou fermé, sans aucun appel `run_now` :
  - `/models/{id}/retrain` ;
  - `/mlops/jobs/{job}/run` (jobs d'entraînement et `drift-monitor`) ;
  - `/training/launch` ;
  - `/runs/{id}/cancel` ;
  - l'acceptation d'une proposition.
- **Nouveau (24cd2dc).** Le serveur refuse désormais de nommer **champion** une version non approuvée, d'après le registre réel. Cela couvre `/models/{id}/promote` et `/mlops/models/{id}/aliases/champion` ; auparavant, seule l'interface le vérifiait.
- **`PUT /models/retrain-mode`.** Il existe désormais un seul système de configuration du réentraînement :
  - `MANUEL` est accepté, sans effet ;
  - `AUTO` est refusé (409) ;
  - `retrainMode` est déduit des politiques réelles : `AUTO` seulement s'il existe une politique automatique active **et** si le planificateur est activé ;
  - l'ancien registre en mémoire `_POLICIES` est supprimé.
- **Le script de démarrage retire** `HOVIS_TRAINING_REMOTE` et `HOVIS_RETRAIN_SCHEDULER`, puis vérifie `launch-guard` et `scheduler` directement et à travers le proxy de l'UI.
- **Rappel des limites de DBX-08 :**
  - budget compté par politique ;
  - un lancement externe concurrent entre le contrôle et la réservation n'est pas exclu ;
  - pas d'authentification réelle : rôle déclaré.

## 4. Audit de performance

### Méthode
- **Sonde navigateur temporaire**, servie par Vite puis supprimée. Elle charge l'application dans Edge headless (le débogage à distance est interdit par la politique du poste, et n'est pas contourné), navigue comme un utilisateur et relève :
  - l'apparition des KPI, tableaux et graphiques ;
  - la fin des requêtes et des états de chargement.
- **Journal serveur** des requêtes, avec leur durée.
- **Compteurs de processus** `/api/mlops/_perf` : requêtes HTTP sortantes (MLflow et SDK Databricks) et lancements du CLI `databricks`. Ils sont actifs uniquement avec `HOVIS_PERF_COUNTERS=1`.
- **Un run de sonde = 23 étapes** : 6 sections AI Leader, 6 détails ou onglets, 6 retours, 4 écrans industriels. Les cellules du tableau donnent le temps, l'étiquette du run (entre parenthèses) et, quand ils sont pertinents, les appels distants bloquants.
- **Limite de la sonde :** un chargement complet ne peut pas être déclaré terminé avant 1,5 s, plancher technique de la mesure.

### Tableau avant / après
| Module | Action | Avant | Après | Appels distants avant → après | Cause | Correction |
|---|---|---|---|---|---|---|
| Datasets | 1ʳᵉ ouverture après démarrage | 11 173 ms (froid) | 201 / 192 ms (avec préchauffage) | 50 HTTP + 3 CLI → 0 | Catalogue construit à la demande | Préchauffage étendu |
| Datasets | Ouverture, cache expiré | 2 812 ms (B2) | 207 ms (A2) | 14 bloquants → 0 bloquant (7 en arrière-plan) | TTL strict de 60 s, relecture bloquante | *Stale-while-revalidate* (GET uniquement) |
| Datasets | 1ᵉʳ détail d'une famille | 2 204–2 290 ms | 211 ms (F1) | 7 → 0 | Index de famille non préchauffé | Index préchauffés |
| Training Factory | Ouverture, cache chaud | 2 624 ms (B3) | 200 ms (A3) | 10 → 0 | `_version_states` : `get_model_version` séquentiel (N+1) relu à chaque expiration | Lectures parallèles bornées et SWR |
| Training Factory | Ouverture, cache expiré | 4 349 ms (B2) | 183 ms (A2) | 15 bloquants → 0 | Idem | Idem |
| Training Factory | Rafraîchissement forcé (`summary`) | 9 272 ms | 3 039 ms | 62 → 37 | Lectures séquentielles par pipeline | Parallélisation bornée avec propagation du contexte |
| Training Factory | Rafraîchissement forcé (`runs`) | 4 356 ms | 3 013 ms | 18 → 18 | Idem | Idem |
| Training Factory | Détail d'un run, cache chaud ou expiré | 2 213 ms (B3) | 158 ms (A3) | 8 → 0 | TTL bloquant | SWR |
| Vue d'ensemble | `models/overview`, cache expiré | 2 006 ms (B2) | 27 ms (A2) | 21 bloquants → 0 bloquant (22 en arrière-plan) | TTL bloquant | SWR |
| Vue d'ensemble | Fin des requêtes (`health` compris) | 2 182 ms (B2) | 604–726 ms | — | `health` (~250–290 ms) vérifie la connexion à chaque visite | Conservé (contrôle réel affiché à part) |
| Model Registry | Ouverture | 151–206 ms | 151–212 ms | 0 → 0 | — | — |
| Deployment Center | Ouverture | 166–202 ms | 158–201 ms | 0 → 0 | — | — |
| Monitoring | Ouverture | 279–744 ms | 212–692 ms | 0 (Core local) | Lecture HTTP du Core de l'instance (12 postes × 2 appels), mise en cache 30 s | SWR (résumé à 20 ms en cache) |
| Politiques | Ouverture ou détail | 157–210 ms | 154–212 ms | 0 → 0 | — | — |
| Toutes | Retour sur une page déjà chargée | 150–210 ms | 150–212 ms | 0 → 0 | Store DBX-PERF-01 | — |
| Démarrage | Préchauffage (arrière-plan, non bloquant) | 36,6 s | 42–47 s | — | Plus de lectures préchauffées | Volontaire |
| Démarrage à froid sans préchauffage | Datasets | 11 173 ms | 11 012 ms | 50 + 3 CLI | Construction initiale et identifiants | Inchangé par nature : couvert par le préchauffage |

Lecture du tableau :
- « 0 bloquant » signifie que l'utilisateur n'attend plus Databricks : les appels distants ont lieu en arrière-plan.
- Avec SWR, la valeur servie porte sa **vraie** date de lecture (`X-HOVIS-Fetched-At`). Les mutations (POST, PUT, DELETE), les lectures `fresh=true` et les clés invalidées après une mutation n'en bénéficient jamais. Elles restent bloquantes et fraîches : aucune approbation ni aucun déploiement ne repose sur une donnée périmée.

### Rafraîchissement forcé (`fresh=true`) d'autres endpoints, après correction
| Endpoint | Temps | Appels distants |
|---|---|---|
| `models/overview` | 3,6 s | 23 |
| `datasets` | 3,6 s | 35 |
| `models/{id}/status` | 2,0 s | 7 |
| `monitoring/summary` | 0,2 s | 0 |
| `retraining/kpis` | 0,02 s | 0 |

Ces temps correspondent au coût réel des lectures Databricks.

### Interfaces industrielles
- **Indépendance du cloud :** 0 appel distant. Elles fonctionnent même si Databricks est indisponible.
- **Premier rendu :**
  - Superviseur : 268–524 ms ;
  - Operator : 165–506 ms ;
  - Cellule : 158–352 ms ;
  - PosteDetail : 161–414 ms.
- **Polling :** chaque requête prend 10 à 130 ms, sur des API locales.
  - Superviseur : 48 à 53 requêtes par fenêtre de 6 s. Il y a un appel KPI par poste (N+1 sur 12 postes) toutes les 4 s.
  - Operator et Cellule : 13 à 31 requêtes par 6 s.
- **Non modifié dans ce chantier.** Une API KPI groupée côté Core réduirait le volume : c'est une proposition pour le responsable RUN.

### Comparaison avec DBX-PERF-01
- **Vue d'ensemble, cache expiré :** DBX-PERF-01 mesurait 0,47 s puis 1,7 s, avec 17 appels. On obtient maintenant 27 ms pour `models/overview`, sans appel bloquant.
- **CLI d'authentification :**
  - DBX-PERF-01 : 6 lancements à froid après sa correction, 13 à 28 avant ;
  - maintenant : 2 à 3 à froid, puis 0.
  
  Le cache d'identifiants n'a donc pas régressé.
- **Écart de périmètre :** les pages Datasets, Training Factory, Monitoring, Politiques et Deployment n'existaient pas lors de DBX-PERF-01. Leurs mesures n'ont pas d'équivalent historique.

### Ressources locales
- **Instance unifiée :**
  - passerelle : 238 Mo résidents / 552 Mo engagés ;
  - Edge : 85 / 411 Mo ;
  - Vite : 160 / 181 Mo.
- **Cause de l'erreur Win32 1455** (« fichier de pagination insuffisant ») : la **mémoire engageable**, et non la RAM. Le fichier d'échange est fixe à 4 Go ; il restait 2,7 Go engageables alors que 11 Go de RAM étaient libres. Chaque passerelle ou serveur MLflow inactif engage environ 550 Mo.
- **Arrêtées (les miennes, remplacées) :** passerelles 8020 et 8023, Vite 5174. Gain : +1,5 Go engageable.
- **Encore actives, non arrêtées** (autres propriétaires, ou origine non établie) :
  - Codex : 8031 et 5177 ;
  - origine non établie : 8024 ;
  - anciennes instances : 5173 (`frontend/`), 8010 (ancien Edge), 8511 (Streamlit) ;
  - démo RUN : 8022 et 18042 ;
  - MLflow : 5000.
  
  Recommandation : les arrêter avec l'accord de leurs propriétaires, et/ou agrandir le fichier d'échange.

## 5. Démarrage unique
```powershell
cd C:\Users\GDYZ5751\Desktop\HOVIS_UNIFIED
powershell -ExecutionPolicy Bypass -File scripts\start_hovis_unified.ps1           # démarrer
powershell -ExecutionPolicy Bypass -File scripts\start_hovis_unified.ps1 -Status   # état
powershell -ExecutionPolicy Bypass -File scripts\start_hovis_unified.ps1 -Stop     # arrêter
```

**Le script :**
- vérifie la branche, Python (`~/ARGOS_MLOPS_LOCAL/.venv` ou `-Python`), Node, `node_modules` et les ports libres (8040, 18040, 5180), et indique le processus qui occupe un port ;
- charge `hovis.local.env` s'il existe (fichier non versionné) ;
- démarre la passerelle, l'Edge (`PIPELINE_ENABLED=false`, source synthétique, `ARGOS_CORE_URL` = passerelle) et Vite avec les drapeaux live ;
- vérifie que Vite sert **ce** worktree avec les drapeaux live, ce qui évite l'ancienne interface de démonstration servie derrière un 200 ;
- écrit les logs dans `var/unified/logs` ;
- **`-Stop`** arrête uniquement ses propres PID, avec leurs enfants (`taskkill /T`).

**URL :**
- recette (point d'entrée unique) : `http://127.0.0.1:5180/` ;
- AI Leader : `/ai-leader` ;
- politiques : `/ai-leader?section=training&view=policies` ;
- Monitoring : `/ai-leader?section=monitoring` ;
- Superviseur : `/superviseur` ;
- Operator : `/operateur?station=SIMUNIF0001-01` ;
- Cellule : `/cellule?station=SIMUNIF0001-11` ;
- PosteDetail : `/superviseur/poste/SIMUNIF0001-01` ;
- API : `http://127.0.0.1:8040/docs` ;
- Edge : `http://127.0.0.1:18040/health`.

## 6. Configuration et persistance
| Donnée | Chemin |
|---|---|
| Core (recette isolée) | `HOVIS_UNIFIED/var/unified/core.sqlite3` (nouvelle base, alimentée par le simulateur, run `UNIF0001`) |
| Edge | `HOVIS_UNIFIED/var/unified/edge.sqlite3` |
| MLOps (cache, lancements, journal d'audit, Monitoring, politiques, Deployment, Package Store) | `%USERPROFILE%\ARGOS_MLOPS_LOCAL` (bases existantes conservées) |
| Logs et PID | `HOVIS_UNIFIED/var/unified/logs`, `pids.json` |
| Identifiants Databricks | Profil CLI `ARGOS` (hors dépôt) |

Le dossier `var/` et les fichiers `*.sqlite*` sont ignorés par Git.

**Attention :** la passerelle Codex 8031 utilise probablement le même `ARGOS_MLOPS_LOCAL`.
- Les accès SQLite multi-processus sont protégés par les verrous de fichier.
- Le registre des lancements (`launches.json`) n'est verrouillé que dans un processus, mais il n'est écrit qu'au lancement, qui est fermé.
- Recommandation : une seule passerelle active une fois `feat/hovis-unified` adoptée.

## 7. Recette

### Fonctionnelle, par API (instance unifiée)
- **Garde-fous :** les 8 routes de lancement ou d'annulation sont refusées.
- **Registre :** promotion d'une version non approuvée refusée ; `retrain-mode AUTO` refusé ; aucun nouveau run.
- **Chaîne industrielle :** 12 postes, 120 pièces, corrections et alertes ; aucun événement Edge en attente.
- **Monitoring :** lit le Core de l'instance (125 inférences, toutes simulées) ; 0 inférence réelle mélangée.
- **Overview v2 :** chaque bloc porte son propre statut.
- **Pages UI :** toutes en 200.

### Visuelle
Elle reste à faire par l'équipe : la politique du poste interdit le pilotage du navigateur. Parcours :
1. Connexion avec chaque rôle.
2. Les 6 sections AI Leader et l'onglet Politiques. Vérifier la bannière « Données simulées » du Monitoring.
3. Le détail d'un run Quality : courbes, matrice de confusion, prédictions.
4. Model Registry : approbations, champion et version servie.
5. Deployment Center : les 12 postes simulés.
6. Superviseur, Operator (corriger une pièce), Cellule et PosteDetail.
7. Liens Monitoring → Politiques.
8. Arrêter la passerelle puis vérifier les états « indisponible ».

## 8. Données scientifiques (sans changement)
- `tri_nok.csv` : seul un **brouillon** existe (`ARGOS_MLOPS_LOCAL/sci-01/tri_nok.draft.csv`). Le fichier rempli par le groupe Quality manque toujours.
- Les quatre jeux Workstation (`poste_5s_11`, `poste_bleu_5s_11`, `poste_variante_5s_11`, `poste_electrique_5s_11`) sont **absents**.

Aucune donnée n'a été fabriquée ni publiée. Le pipeline Workstation n'est pas exécutable ; les politiques ne peuvent pas le cibler, car aucune spécification de pipeline Workstation n'est déclarée.

## 9. Tests
- **Python :** `pytest tests usecases mlops/tests` donne **377 réussis, 11 ignorés**. Les tests ignorés exigent des ressources externes : `ARGOS_DBX_IT`, serveur MLflow, privilège de lien symbolique Windows. Aucun échec.
- **`ruff check .` :** propre.
- **TypeScript :** `tsc` propre.
- **Builds Vite :** par défaut, AI Leader réel, et AI Leader + industriel live — tous réussis.
- **Frontend :** aucune suite de tests (ni script `test`, ni framework).
- **`git diff --check` :** propre, sauf des lignes de contexte du patch `.patch` livré par Safety, laissé tel quel.

## 10. État Databricks (lectures seules, après le chantier)
- **quality_demo :** v1 challenger, non approuvée ; v2 champion, approuvée et servie ; v3 et v4 candidates.
- **quality_industrial :** v1 candidate.
- **Endpoint `argos-quality-poc` :** READY, sert v2.
- **Runs :** 7 runs de jobs, dont le dernier est 741986436941977 (aucun nouveau).
- **Warehouse :** STOPPED, démarrage automatique désactivé.
- **Datasets publiés :** inchangés (`quality-synthetic` synthetic-v2, `quality-synthetic-3c` v1).

Aucune ressource distante créée.

## 11. Limites et blocages restants
- **À décider :** l'intégration de l'interface TeamLeader du groupe Interface (conflit avec Superviseur live), le dépôt orphelin détection-téléphone et le patch Operator de Safety.
- **Travail en cours** non committé dans `HOVIS_INDUSTRIAL`, non repris.
- **Safety a publié 4 nouveaux commits pendant le chantier** (`origin/EPI` df06ba9 → dd33949, 04:38–05:35, dont « YOLO26s is the chosen model »). Ils ne sont pas repris : la livraison évolue encore. Après confirmation du groupe : `git checkout origin/EPI -- usecases/safety`, puis `pytest usecases/safety tests/test_contract.py`.
- **Données scientifiques manquantes** (§8).
- **Démarrage à froid sans préchauffage :** les 11 s du catalogue Datasets restent possibles juste après un redémarrage, pendant les 42 à 47 s du préchauffage.
- **Rafraîchissement forcé :** 2 à 4 s par endpoint, soit le coût réel de Databricks.
- **Polling N+1 du Superviseur :** local et rapide, mais 12 appels KPI toutes les 4 s.
- **Marge mémoire faible** tant que les autres instances tournent (§4).
- **Pas de tests frontend automatisés.**
