# DBX-02 — Intégration des chantiers et AI Leader en direct

## Branche et commits intégrés

Branche locale `feat/argos-integration`, créée depuis DBX-01 (`c247d1a`).

| Origine | Commits | Fusion |
|---|---|---|
| MLOps (Claude) | MLOPS-01 `f8905bf`, DBX-00 `3359e6a`, DBX-01 `c247d1a` | base de la branche |
| Core (Codex, `feat/argos-core`) | CORE-01 `9b1bafb`, CORE-02 `ab8adef` | merge `0fd7b88`, sans conflit |
| Frontend + EPI (`origin/interface`) | `b8a9e04`, `b55588e`, `99ad5f1`, `461634f` | merge `4ec75ab`, sans conflit |

Aucun fichier n'était modifié par deux origines à la fois. Les branches originales et le worktree `ARGOS_CORE` n'ont pas été touchés.

## Architecture opérationnelle

```text
Navigateur ──► argos-ui (Vite, 127.0.0.1:5174) ──/api──► passerelle 127.0.0.1:8020
                                                          ├─ Core de Codex (inchangé) : /health, /ingest/v1/events, /api/v1/*
                                                          └─ routeur MLOps DBX-01     : /api/models/*, /api/mlops/*
                                                                 └─► Databricks (profil OAuth ARGOS, côté serveur uniquement)
```

`mlops/api/platform.py` appelle `visionhub.core.app.create_app()` sans le modifier, puis ajoute `create_mlops_router()` sous `/api`. Il vérifie avant l'inclusion qu'aucune route n'est en double (20 routes Core et 25 routes MLOps, aucune collision).

## Démarrer

```powershell
powershell -ExecutionPolicy Bypass -File mlops\scripts\start_argos_live.ps1
# ARGOS : http://127.0.0.1:5174 → identifiant a.noui@hutchinson.com (rôle AI Leader, démo) → /ai-leader
```

Équivalent en deux terminaux :

```powershell
# 1. passerelle (venv MLOps)
Set-Location C:\Users\<vous>\Desktop\HACKHATON
$env:ARGOS_CORE_DB = "var/argos-integration-core.sqlite3"
& "$env:USERPROFILE\ARGOS_MLOPS_LOCAL\.venv\Scripts\python.exe" -m uvicorn mlops.api.platform:app --host 127.0.0.1 --port 8020
# 2. interface
Set-Location C:\Users\<vous>\Desktop\HACKHATON\argos-ui
$env:VITE_LIVE_AI_LEADER = "true"; $env:ARGOS_API_TARGET = "http://127.0.0.1:8020"
npx vite --host 127.0.0.1 --port 5174 --strictPort
```

## Configuration réel / démo

| Variable | Effet |
|---|---|
| `VITE_LIVE_AI_LEADER=true` | **seul** l'écran AI Leader utilise les données réelles ; les autres écrans gardent leurs mocks |
| `VITE_USE_MOCK=false` | tous les écrans appellent le backend (Opérateur, Superviseur et Admin attendent des routes `/api/*` qui n'existent pas encore côté Core : à raccorder plus tard) |
| `ARGOS_API_TARGET` | cible du proxy Vite `/api` (défaut inchangé : `http://localhost:8000`) |

Tant que des mocks sont actifs, un badge permanent « Démo · données simulées (sauf AI Leader : données réelles) » est affiché.

## Écran AI Leader en direct (`argos-ui/src/pages/AiLeaderLive.tsx`)

| Bloc | Source réelle | Comportement si indisponible |
|---|---|---|
| Connexion Databricks (barre du haut) | `GET /api/mlops/health` (toutes les 60 s) | pastille rouge avec la cause |
| Modèles | `GET /api/models/overview` | message d'erreur, aucune valeur de repli |
| Emplacements Quality Inspection, PPE Detection, Behavior Detection | — | « En attente de livraison · Groupe … » (aucun faux modèle) |
| Registre (par modèle géré) | `/api/mlops/models/{id}/status` + `/api/mlops/runs/{run}` | erreur affichée |
| Comparaison de versions | `GET /api/mlops/runs/compare` | erreur affichée |
| Entraînements | `/api/mlops/experiments`, `/runs`, `/api/mlops/jobs` | erreur affichée |
| Model Serving | `GET /api/mlops/endpoints` | erreur affichée |
| Monitoring | `GET /api/mlops/models/{id}/monitoring` | lecture en direct impossible si le warehouse est arrêté (jamais démarré automatiquement) ; le **dernier résultat connu** est affiché avec sa date de lecture |
| Santé sur 14 jours | — | « Historique indisponible » : aucune courbe simulée |

Le registre affiche, pour chaque version : alias, approbation, version servie, dataset, date d'entraînement, métriques MLflow et run MLflow. Les trois notions sont rappelées par trois pastilles (approuvée = tag, champion = alias UC, servie = endpoint).

## Actions

| Action | Statut |
|---|---|
| Approuver une version | **opérationnelle** (tag UC), avec confirmation |
| Définir le champion | **opérationnelle** (alias UC), avec confirmation qui précise que la version servie ne change pas |
| Relancer l'entraînement | **opérationnelle** : le job existant est déclenché, puis suivi toutes les 10 s pendant 10 min au plus ; refus 409 si un run est actif |
| Mode MANUEL / AUTO | préférence enregistrée **en mémoire** ; libellée « préférence », aucune automatisation |
| Actualiser le monitoring | relit si le warehouse tourne déjà ; ne le démarre jamais |
| Changer la version servie (déploiement) | **non disponible**, et aucun bouton factice |

## Validation et limites

- La navigation dans un navigateur automatisé est **impossible sur ce poste** : « DevTools remote debugging is disallowed by the system admin » (stratégie d'entreprise d'Edge). Elle n'a pas été contournée. Les vérifications ont été faites par HTTP, via le proxy de l'interface, sur les mêmes routes que la page. **Le contrôle visuel reste à faire** dans un navigateur.
- Quand la passerelle est arrêtée, le proxy renvoie un 500 et l'écran affiche « Backend ARGOS injoignable », sans aucune donnée de repli.
- `healthPct` : exactitude étiquetée du monitoring en direct, sinon exactitude de validation du run servi (libellé à l'écran).
