# Trame du pitch (brouillon à retravailler en équipe)

La vidéo tourne sans son : l'orateur commente ce qui se passe à l'écran.
Les temps sont indicatifs (5 min au total) : vérifiez-les dans le Studio, dont la timeline affiche chaque étape.

Rappel du contexte client : l'usine est découpée en **UAP**, chaque UAP en **cellules**, chaque cellule en **postes** (12). HOVIS travaille au niveau de la cellule.

| ≈ Temps | À l'écran | Idée à dire |
|---|---|---|
| 0:00 | Logo HOVIS | Qui on est, la promesse : « Smarter vision. Safer industry. » |
| 0:12 | **Titre : l'opérateur, au poste** (tablette) | À chaque cycle, qualité, poste et sécurité doivent être vérifiés. |
| 0:16 | Connexion, écran tout au vert | Pièce conforme, objectif du shift, cadence heure par heure (le surplus remplit l'heure suivante). |
| 0:50 | Pièce KO (zoom sur la pièce) | La caméra voit 2 joints : consigne immédiate, pièce au bac rebuts. |
| 1:03 | EPI manquant, puis plusieurs problèmes | Alerte au poste (voir la remarque ci-dessous) ; l'écran donne les actions dans l'ordre, la sécurité d'abord. |
| 1:23 | Signaler un problème | Un geste et le team leader est prévenu. |
| 1:30 | **Titre : la TV de la cellule** | |
| 1:34 | TV : 12 tuiles vertes, orange, rouges | Toute l'équipe voit la performance des postes, de loin. Uniquement la production : ni alerte sécurité, ni nom. |
| 1:50 | **Titre : le team leader, depuis son PC** | Le team leader gère les 12 postes de sa cellule. |
| 1:54 | Tableau des postes, filtre « Sécurité » | Il voit l'état, le rythme, les KO et les alertes de chaque poste ; il filtre ce qui demande son attention. |
| 2:15 | Écran du poste P06 en consultation | Il ouvre exactement l'écran de l'opérateur, sans se déplacer, et prend l'alerte en charge. |
| 2:35 | Courbe de production de la cellule | Le réel face à l'objectif : l'écart donne l'avance ou le retard. |
| 2:51 | Alertes, valider, historique du poste | Il valide ou rejette en un clic ; l'historique du shift est celui du poste, jamais de la personne. |
| 3:25 | **Titre : l'AI Leader** | |
| 3:29 | Santé des modèles, dérive, promotion | Les modèles sont suivis ; une dérive se corrige par un réentraînement validé par un humain. |
| 4:03 | **Titre : l'administrateur** | |
| 4:07 | Utilisateurs, rôles, journal | Chacun ne voit que ce qui le concerne, tout est tracé. |
| 4:48 | Logo, « Merci » | Conclusion et suite (pilote sur une cellule…). |

## À vérifier avant le pitch

- **Visages floutés** : l'interface l'affiche, mais `anonymize()` dans `visionhub/preprocess.py` n'applique encore aucun floutage. Si ce n'est pas fait d'ici là, dites « prévu ».
- **Données** : tous les chiffres à l'écran sont des données de démonstration (`argos-ui/src/api/mock.ts`). Présentez-les comme une démo, pas comme des résultats mesurés.
- **Seuil de la TV** : orange jusqu'à 10 pièces de retard, rouge au-delà. Valeur à confirmer par le client (`TOLERANCE` dans `argos-ui/src/pages/CelluleTV.tsx`).
