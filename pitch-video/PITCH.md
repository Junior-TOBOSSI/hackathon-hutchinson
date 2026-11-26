# Trame du pitch (brouillon à retravailler en équipe)

La vidéo tourne sans son : l'orateur commente ce qui se passe à l'écran.
Les temps sont indicatifs (environ, pour 5 min) : vérifiez-les dans le Studio, dont la timeline affiche chaque étape.

| ≈ Temps | À l'écran | Idée à dire |
|---|---|---|
| 0:00 | Logo HOVIS | Qui on est, la promesse : « Smarter vision. Safer industry. » |
| 0:12 | **Titre : l'opérateur, au poste** (tablette) | Le problème : à chaque cycle, qualité, poste et sécurité doivent être vérifiés. |
| 0:16 | Connexion sur la tablette | L'opérateur se connecte (ou passe son badge). |
| 0:25 | Écran opérateur, tout au vert | Pièce conforme, objectif du shift, cadence heure par heure. |
| 0:41 | Zoom sur la barre heure par heure | Le surplus d'une heure remplit la suivante, le trait marque où on devrait être. |
| 0:52 | Pièce KO (zoom sur la pièce) | La caméra voit 2 joints : consigne immédiate, pièce au bac rebuts. |
| 1:08 | EPI manquant | Alerte au poste, visage flouté (voir la remarque ci-dessous). |
| 1:24 | Plusieurs problèmes | L'écran donne les actions dans l'ordre, la sécurité d'abord. |
| 1:38 | Signaler un problème | Un geste et le superviseur est prévenu. |
| 1:46 | **Titre : le superviseur, depuis son PC** | |
| 1:50 | Vue d'ensemble, production, alertes | Tout l'atelier d'un coup d'œil ; il valide ou rejette les alertes. |
| 2:45 | Détail d'un poste | Le shift du poste : épisodes, EPI, alertes. Sans nom ni classement d'opérateur. |
| 3:00 | **Titre : l'AI Leader** | |
| 3:04 | Santé des modèles, dérive, promotion | Les modèles sont suivis ; une dérive se corrige par un réentraînement validé par un humain. |
| 3:45 | **Titre : l'administrateur** | |
| 3:49 | Utilisateurs, rôles, journal | Chacun ne voit que ce qui le concerne, tout est tracé. |
| 4:48 | Logo, « Merci » | Conclusion et suite (pilote sur une ligne…). |

## À vérifier avant le pitch

- **Visages floutés** : l'interface l'affiche, mais `anonymize()` dans `visionhub/preprocess.py` n'applique encore aucun floutage. Si ce n'est pas fait d'ici là, dites « prévu ».
- **Données** : tous les chiffres à l'écran sont des données de démonstration (`argos-ui/src/api/mock.ts`). Présentez-les comme une démo, pas comme des résultats mesurés.
