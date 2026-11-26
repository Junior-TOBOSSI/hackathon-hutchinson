# CORE-02 proposé — raccordement Edge → Core

CORE-01 reçoit déjà `EdgeEventBatch` sur `POST /ingest/v1/events`, mais **l'Edge actuel ne lui envoie rien**. Aucun raccordement ne doit être revendiqué avant l'ajout et le test d'une outbox transactionnelle.

## Points d'extension existants

| Fait | Écriture Edge actuelle | Événement à publier dans la même transaction |
|---|---|---|
| Cycle et pièce | `ProductionEngine.run_cycle()` puis `ProductionStore.insert_part()` ; l'événement d'inférence et la pièce sont écrits ensemble si l'inférence réussit. | `inference` si présent, puis `part.recorded` pour tout cycle, y compris `ERROR`. |
| Correction humaine | `ProductionStore.add_correction()` ajoute l'historique et change le verdict effectif. | `part.corrected` avec `Correction.sequence`. |
| Disposition physique | `ProductionStore.set_disposition()`. | `part.disposition`, sans déduire la disposition du verdict. |
| Shift | `ProductionStore.insert_shift()` et `close_shift()`. | `shift.opened`, `shift.closed`. |
| État caméra / modèle | Pas de publication métier commune vérifiée. | `equipment.status`, `model.status` au point où l'état réel est connu. |
| Safety / Workstation | `Pipeline.process_frame()` produit des événements d'inférence. | `inference`, sans image ni identité personnelle. |
| Signalement opérateur | Contrat présent, endpoint Edge encore absent. | `operator.report` après écriture locale du signalement. |

Le `POST /events/{id}/feedback` historique n'est **pas** une correction de pièce. La correction de production passe par `/production/parts/{id}/corrections`. Il faut éviter de publier deux événements pour une seule action et éviter une seconde inférence côté Core.

## Transaction et rejeu

Ajouter au SQLite Edge une table d'outbox avec `edge_sequence` croissant par poste, `event_id` unique, payload sérialisé, `delivered_at`, tentatives et erreur. Dans **la transaction du fait métier**, insérer la ligne outbox correspondante. Sans cette atomicité, une panne peut créer une pièce sans événement transférable. Cette évolution touche `visionhub/production/` et les fichiers partagés : elle appartient à **CORE-02**, sous revue de l'Intégration, et n'est pas faite ici.

Un expéditeur Edge envoie des lots triés (maximum 500), attend `IngestAck`, puis marque seulement les lignes `accepted` ou `duplicate` comme livrées. `rejected` reste en outbox pour investigation. En cas de timeout ou de `503`, il redemande l'état et rejoue **le même `event_id` et le même contenu** avec backoff borné. Le Core distingue un rejeu exact d'un même ID portant un autre contenu. `highest_contiguous_sequence` aide à repérer les trous. Ne jamais purger un événement non acquitté. Aucun transfert d'image ou de visage.

Le fonctionnement local de l'Edge doit continuer pendant la perte de connexion Core. À la reconnexion, l'outbox est vidée dans l'ordre ; le Core accepte néanmoins les arrivées tardives et reconstruit les projections. Des tests d'intégration devront couvrir panne avant/après commit, coupure réseau, ACK perdu, doublons et corrections reçues avant leur pièce.
