# Données

> **Rien de ce dossier n'est versionné**, sauf ce fichier (voir `.gitignore`). Les données restent sur les machines de l'équipe et ne sont **jamais** envoyées vers un service externe.

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
└── test/         # JEU DE TEST MIS DE CÔTÉ dès le départ
    ├── quality/
    ├── workstation/
    └── safety/
```

## Règles

1. **`test/` n'est jamais utilisé pour l'entraînement ni pour régler les seuils.** On le constitue au début, on n'y touche plus, et on ne s'en sert que pour mesurer les résultats finaux (présentés au jury).
2. On ne modifie jamais `raw/` : toute transformation produit des fichiers dans `processed/`.
3. Les poids de modèles (`*.pt`, `*.onnx`, `*.ckpt`, dossiers OpenVINO…) ne sont pas versionnés non plus. Partagez-les entre vous par clé USB ou dossier partagé interne.
4. Images de personnes (cas `safety`) : ne conservez que le strict nécessaire, ne publiez rien, et supprimez tout à la fin du hackathon.
