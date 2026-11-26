# HOVIS : vidéo de pitch (Remotion)

Vidéo de 5 min, **sans son**, projetée derrière l'orateur : on y voit **l'interface HOVIS utilisée sur une tablette (opérateur au poste) puis sur un PC (superviseur, AI Leader, administrateur)**.

Elle se fabrique en deux temps :

1. **Capture** (`capture/record.mjs`) : un script pilote la vraie interface (`../argos-ui`, données de démo) dans Microsoft Edge, comme un utilisateur (connexion, clics, onglets). À chaque étape, il enregistre une capture nette et la position de l'élément cliqué ensuite.
2. **Montage** (Remotion, `src/`) : chaque capture est placée dans un cadre de tablette ou de PC. Un doigt ou une souris va cliquer au bon endroit, la caméra zoome sur les moments clés, et une légende courte accompagne chaque étape. Une ouverture et une fin au logo HOVIS encadrent le tout.

## Démarrer

```bash
cd pitch-video
npm install
npm run capture       # construit l'interface et enregistre la démo (≈ 1 min)
npm run studio        # aperçu sur http://localhost:3000
```

## Produire la vidéo

```bash
npm run render -- --browser-executable="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
# → out/hovis-pitch.mp4 (1920 × 1080, 30 i/s, 5 min)
```

Tout se fait en local : aucune donnée n'est envoyée à un service externe.

## Modifier la démo

| Je veux… | Où |
|---|---|
| changer le parcours, une légende ou la durée d'un écran | `STEPS` dans `capture/record.mjs`, puis `npm run capture` |
| changer la durée totale (5 min par défaut) | `TARGET_SECONDS` dans `src/timeline.ts` |
| changer le cadre de la tablette ou du PC | `src/demo/Device.tsx` |
| changer le curseur, le doigt ou le zoom | `src/demo/Pointer.tsx`, `src/demo/StepView.tsx` |
| changer l'ouverture ou la fin | `src/scenes/Intro.tsx`, `src/content.ts` |

Les durées (`hold`) sont **relatives** : elles sont toutes étirées ou resserrées pour que la vidéo dure exactement `TARGET_SECONDS`. Donner plus de temps à un écran revient donc à en prendre aux autres.

Si l'interface change, il suffit de relancer `npm run capture` : la vidéo reprend les nouveaux écrans.

## Détails techniques (pour le jury)

- **Capture** : `playwright-core` pilote l'Edge déjà installé (pas de navigateur téléchargé). Deux fenêtres sont simulées : tablette 1280 × 800 tactile et PC 1440 × 900, en double résolution. L'horloge est fixée à 16:51 pour que tous les écrans soient cohérents. La barre « Démo » de l'interface est masquée : les changements de scénario (pièce KO, EPI…) apparaissent comme de vraies détections.
- **Montage** : une vidéo Remotion est un composant React rendu image par image. `src/timeline.ts` construit la ligne de temps à partir de `public/capture/steps.json`, et `src/demo/StepView.tsx` anime chaque étape (fondu, trajet du pointeur, clic, zoom) en fonction du numéro d'image.
- `remotion.config.ts` force une seule copie de React, parce que les composants importés depuis `../argos-ui` (logo, charte) chercheraient sinon la leur.

## Licence Remotion

Remotion est gratuit pour les particuliers et les structures de 3 personnes maximum. Au-delà, une licence entreprise est demandée : vérifier sur <https://www.remotion.dev/license> si la vidéo est réutilisée hors du hackathon.

## Règles

- Ne jamais versionner la vidéo rendue ni les captures (`out/` et `public/capture/` sont dans `.gitignore`).
- Les visuels de démonstration de l'interface sont des dessins, pas des images réelles de pièces ou de personnes.
