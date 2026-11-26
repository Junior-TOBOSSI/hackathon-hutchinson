# CORE-01 — preuves de validation locale

Constat du **26 novembre 2026, vers 20 h 12 (Europe/Berlin)**. Les commandes ci-dessous ont été lancées dans `C:\Users\GDYZ5751\Desktop\ARGOS_CORE` avec **son propre** `.venv\Scripts\python.exe` (Python 3.11.9). Aucune opération Databricks ou MLflow n'a été effectuée.

| Contrôle | Résultat observé |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest` | **134 passed**, 1 avertissement de dépréciation FastAPI/TestClient, 22,95 s au dernier passage. Inclut les tests de contrat et les 10 tests Core dans `tests/core/`. |
| `.\.venv\Scripts\python.exe -m ruff check .` | `All checks passed!` |
| `.\.venv\Scripts\python.exe -m ruff format --check .` | `60 files already formatted` |

## HTTP réel

Serveur démarré temporairement sur `127.0.0.1:8020`, arrêté ensuite. Le simulateur a utilisé exclusivement des faits synthétiques et `POST /ingest/v1/events` ; aucune écriture directe dans les projections.

| Vérification | Résultat |
|---|---|
| Simulation sur base neuve | 12 postes ; 218 événements `accepted`, puis 218 `duplicate` lors du rejeu exact ; 0 `rejected`. |
| Persistance / agrégation | `GET /health` → 12 postes, 218 événements, 88 pièces. `GET /api/v1/kpi` → 69 OK, 13 NOK, 5 HOLD, 1 ERROR ; somme = 88 ; taux de conformité = 69/88 = 0,78409. |
| Statuts poste | 11 postes en ligne, `WS-12` inactif ; tous marqués `simulated=true`. |
| Correction | Une pièce `WS-02` garde `predicted_verdict=NOK` et reçoit `effective_verdict=OK` ; l'historique de correction compte 1. |
| Alertes | 26 épisodes ; trois observations Safety d'un poste groupées dans un épisode ; un épisode résolu par HTTP. |
| Redémarrage | Arrêt puis redémarrage du serveur sur la **même base** : 12 postes, 218 événements, 88 pièces, correction et alerte résolue conservées. |

Les bases de cette validation sont dans `var/` (ignoré par Git). Le Core n'est pas encore raccordé à l'outbox Edge ni à un frontend en mode live. Le simulateur ne mesure aucune performance de modèle de Computer Vision.

Un passage complet intermédiaire a échoué sur une allocation mémoire NumPy de 7 Mio dans le test historique `tests/production/test_api_production.py::test_acceptance_scenario`. Ce test a réussi isolément immédiatement après, puis les **134 tests** ont réussi au passage complet suivant. Aucun fichier de ce test ou du Production Engine n'a été modifié.

## CORE-02 — liaison Edge → Core, 26 novembre 2026

La validation HTTP a utilisé deux bases neuves et distinctes dans `var/`, ignoré par Git. Core : `127.0.0.1:8020` ; Edge : `127.0.0.1:18040` avec `ARGOS_CORE_URL=http://127.0.0.1:8020`. Le simulateur `visionhub.production.plc_sim` a appelé les vrais endpoints de cycles du Production Engine, qui ont exécuté `FakeQualityAnalyzer`. Aucun appel Databricks, aucune inférence Core.

| Contrôle | Résultat observé |
|---|---|
| Simulateur PLC initial | 3 nouveaux cycles HTTP `201`, 1 rejeu `200` avec `Idempotent-Replay: true` ; Core : 3 pièces, 7 événements (shift ouvert, 3 inférences, 3 pièces), outbox : 7 livrés et 0 en attente. |
| Correction et disposition | Une pièce passe de `effective_verdict=OK` à `NOK` via `/production/parts/{id}/corrections`, garde `predicted_verdict=OK`, puis reçoit `QUARANTINED`. Core : 3 pièces, 2 OK, 1 NOK, 1 corrigée ; 9 événements livrés. |
| Core interrompu | Un nouveau cycle `201` et une correction `201` sont acceptés par l'Edge pendant l'arrêt du Core. L'outbox conserve 3 événements, avec erreur réseau constatée. |
| Redémarrage et rattrapage | Edge redémarré sur la même base pendant la coupure, puis Core redémarré sur sa même base : outbox 12 livrés, 0 en attente ; Core 4 pièces, 12 événements, 2 corrections, sans pièce dupliquée. |
| Alertes et shift | Seuils de démonstration abaissés par l'API Edge ; un nouveau cycle NOK `201` crée les alertes `quality.decision` et `part.nok` dans `/api/v1/alerts`. Fermeture du shift synchronisée : Core 5 pièces, 15 événements, 2 alertes ouvertes ; outbox 15 livrés, 0 en attente. |
| Non-régression | Suite complète `pytest -q` : succès (140 tests collectés, dont 6 CORE-02). `ruff check .` : `All checks passed!`. `ruff format --check .` : `63 files already formatted`. `git diff --check` : succès. |

Le premier passage complet a échoué sur `test_exported_artifacts_are_up_to_date` : la nouvelle route de diagnostic Edge apparaissait dans l'OpenAPI exporté du frontend. La route a été conservée mais exclue du schéma OpenAPI public (`include_in_schema=False`), afin de respecter le périmètre sans modifier `frontend/`. `python -m visionhub.integration.export --check` et le passage complet suivant ont réussi. L'absence d'authentification impose de garder les deux API sur localhost ; les événements rejetés par le Core restent conservés en outbox pour diagnostic manuel.
