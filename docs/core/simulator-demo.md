# SIM-01 — démonstration industrielle synthétique

Le script `scripts/argos_demo.py` orchestre les API déjà présentes. Il ne modifie ni le Core, ni le Production Engine, ni les contrats, ni les modèles. Par défaut, il montre **12 postes** : **10 postes de production** avec cycles PLC simulés via le Production Engine et son outbox, plus **2 postes réservés** aux faits synthétiques directement ingérés par le Core. Un poste n'a qu'un seul producteur d'événements ; les séquences Edge et Core ne se mélangent jamais. Tous les identifiants de poste portent `SIM<run-id>-` et chaque lancement reçoit un identifiant aléatoire distinct, sauf `--run-id` explicite.

## Commandes PowerShell

Depuis `C:\Users\GDYZ5751\Desktop\ARGOS_CORE` :

```powershell
# Mode autonome : démarre et arrête uniquement ses deux serveurs dédiés.
.\.venv\Scripts\python.exe scripts/argos_demo.py --mode autonomous --scenario full --duration 60 --rate 2 --stations 12 --direct-stations 2 --nok-rate 0.10

# Variante bornée avec ports choisis ; les ports par défaut sont 18220 (Core) et 18240 (Edge).
.\.venv\Scripts\python.exe scripts/argos_demo.py --mode autonomous --scenario full --duration 15 --rate 3 --core-port 18420 --edge-port 18440 --run-id JURY0001

# Mode raccordé : utiliser uniquement des instances déjà démarrées. Le script ne les arrête
# pas, ne les redémarre pas et ne change aucun seuil ni configuration de service.
.\.venv\Scripts\python.exe scripts/argos_demo.py --mode connected --core-url http://127.0.0.1:8020 --edge-url http://127.0.0.1:8000 --scenario full --duration 60 --run-id JURY0002
```

En mode autonome, les bases et journaux propres au lancement sont dans `var/sim/<run-id>/` (ignoré par Git). Le script refuse les ports occupés et un dossier de simulation déjà présent. En mode raccordé, **les deux URL sont obligatoires** ; seules les origines HTTP loopback avec port explicite sont acceptées. Le script vérifie l'absence des identifiants de postes envisagés dans le Core et dans les pièces ou shifts de l'Edge avant toute émission. Il refuse un `run-id` déjà utilisé. Ne pointer le mode raccordé que vers l'Edge et le Core souhaités pour la démonstration ; les événements synthétiques resteront enregistrés dans leurs bases.

Le script affiche périodiquement les KPI et états, puis une ligne `FINAL` en JSON. `observed_nok_rate` correspond au verdict **effectif** dans le Core, après correction ; `predicted_nok_rate` correspond aux prédictions des cycles produits ; tous deux sont distincts de `target_nok_rate`. `edge_pending_global` et `edge_rejected_global` concernent toute l'instance Edge en mode raccordé, et peuvent donc inclure d'autres postes. La durée borne la phase active ; la fermeture des shifts et l'attente d'acquittement peuvent ajouter jusqu'à 12 secondes.

## Scénarios

| `--scenario` | Progression visible |
|---|---|
| `normal` | Cycles et KPI des postes de production, shifts ouverts puis fermés. |
| `quality` | Production normale, puis trois cycles ciblés sur un poste qualité et une correction synthétique. |
| `multiple` | Dégradation qualité, trois observations Safety regroupées, deux Workstation regroupées, statut caméra `down`, correction et résolution des alertes. |
| `disconnect` | **Autonome uniquement** : le Core enfant est arrêté puis redémarré ; les cycles continuent sur l'Edge et l'outbox est rattrapée. |
| `full` (défaut) | Tous les éléments précédents ; un poste synthétique commence hors ligne puis revient en ligne. En mode raccordé, l'étape d'arrêt du Core est omise. |

`--rate` règle le nombre **total** de cycles par seconde, `--duration` la durée active en secondes, `--stations` le nombre total de postes et `--direct-stations` le nombre réservé aux événements Core synthétiques. `multiple` et `full` nécessitent au moins deux postes directs ; il faut toujours au moins un poste de production. `--seed` fixe la répartition des cycles NOK visés. Un `Ctrl+C` arrête la simulation et, en mode autonome seulement, ses deux processus enfants.

## Origine des événements et limites

- Chaque pièce est créée par `POST /production/stations/{id}/cycles` avec `simulated=true`, comme dans `plc_sim`. L'Edge effectue l'analyse de démonstration et publie l'inférence et la pièce via l'outbox CORE-02. Les corrections utilisent `POST /production/parts/{id}/corrections`. Aucun accès direct aux bases n'écrit des faits.
- Le simulateur Core existant a fourni les contrats et exemples d'incidents ; son lot complet n'est pas réinjecté, car il contiendrait aussi des pièces et des séquences concurrentes. Les deux postes réservés reçoivent seulement des événements `simulated=true` de Safety, Workstation, caméra et, si nécessaire, une alerte qualité synthétique de secours. Ces observations ne sont **pas** des détections réelles, ni des constats de panne matérielle. Aucun visage, image, donnée industrielle ou appel Databricks n'est utilisé.
- Si l'API Edge annonce `fake-quality`, le script choisit des `cycle_id` synthétiques dont l'analyseur factice existant devrait produire le verdict souhaité avec sa configuration de référence. Il ne change pas les seuils. Si la configuration factice diffère, ou si un véritable adaptateur remplace l'analyseur, `--nok-rate` devient une cible indicative : le script affiche toujours le taux observé. En mode raccordé, il ne reconfigure jamais l'Edge. Une alerte qualité synthétique sur un poste réservé sert de secours si aucun cycle NOK n'a été prédit.
- L'état hors ligne est simulé par un événement horodaté dix minutes auparavant sur un poste réservé, puis par une observation récente qui le remet en ligne. `online` reste une mesure de fraîcheur des événements, pas un heartbeat industriel. La résolution d'une alerte est un appel explicite à `POST /api/v1/alerts/{id}/resolve` ; un statut caméra `ok` ne la résout pas automatiquement.
- Les événements directs du script sont rejoués en mémoire avec le même `event_id` pendant une coupure du Core, mais ils ne disposent pas de l'outbox persistante de l'Edge. La garantie de reprise après redémarrage concerne les faits de production du Production Engine. Les API locales n'ont pas d'authentification : le script n'accepte que localhost.

## Validation locale du 26 novembre 2026

Deux exécutions bornées du scénario `full` ont utilisé uniquement les bases ignorées de ce worktree et des ports dédiés. En mode autonome (10 s, 3 cycles/s visés), le Core final comptait 12 postes et 26 pièces pour 26 cycles effectivement produits ; l'outbox Edge avait 0 événement en attente et 0 rejeté. Les KPI sont passés progressivement de 0 à 26 pièces ; le poste hors ligne est redevenu en ligne ; les alertes Safety ont regroupé 3 observations, 5 alertes ont été résolues et une correction a changé le KPI. Le Core enfant a été interrompu puis redémarré, et les événements Edge ont été rattrapés.

En mode raccordé sur une autre paire de serveurs de test (8 s, 3 cycles/s visés), les API étaient encore disponibles après l'arrêt du script. Le Core comptait 12 postes, 24 pièces pour 24 cycles, 78 événements dont 9 synthétiques directs ; l'outbox Edge indiquait 69 événements livrés, 0 en attente et 0 rejeté. Le taux NOK effectif final était 12,5 % pour une cible de 10 %, distinct du taux prédit de 16,7 %. Le plus grand épisode comptait 3 observations et 5 alertes étaient résolues. Les serveurs de test ont ensuite été arrêtés manuellement. La suite de non-régression a donné **140 tests réussis** ; Ruff check et format sont propres.
