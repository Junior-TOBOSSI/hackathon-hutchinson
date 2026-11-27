# Données

> **Ce dossier est versionné** depuis le 2026-11-27, avec l'accord de Hutchinson (voir `AGENTS.md`). Les poids (`models/`) et les vidéos (`raw/safety/videos/`) passent par **Git LFS** : faire `git lfs install` une fois par machine avant de cloner, sinon ces fichiers arrivent comme de petits fichiers texte « pointeurs ».

## Organisation attendue

```
data/
├── raw/          # données brutes telles que reçues (images, vidéos) — lecture seule
│   ├── quality/
│   ├── workstation/
│   └── safety/
├── processed/    # données préparées : recadrées, redimensionnées, annotées, découpées train/val
│   ├── quality/
│   ├── workstation/
│   └── safety/
├── test/         # JEU DE TEST MIS DE CÔTÉ dès le départ
│   ├── quality/
│   ├── workstation/
│   └── safety/
└── models/       # poids des modèles (*.pt, *.ckpt, *.onnx…), un dossier par cas d'usage
```

## Règles

1. **`test/` n'est jamais utilisé pour l'entraînement ni pour régler les seuils.** On le constitue au début, on n'y touche plus, et on ne s'en sert que pour mesurer les résultats finaux (présentés au jury).
2. On ne modifie jamais `raw/` : toute transformation produit des fichiers dans `processed/`.
3. Les poids de modèles se rangent dans `data/models/<cas>/` ; ils sont versionnés avec Git LFS. Toute nouvelle donnée client doit avoir l'accord de Hutchinson avant d'être poussée (le dépôt est public).
4. Images de personnes (cas `safety`) : ne conservez que le strict nécessaire, ne publiez rien, et supprimez tout à la fin du hackathon.
