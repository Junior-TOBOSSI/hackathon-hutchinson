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
