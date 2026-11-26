# ARGOS Frontend

Une application React pour trois espaces :

| Route | Persona | Backend |
|---|---|---|
| `/operator` | Opérateur (un poste) | **Edge** local (`VITE_EDGE_API_URL`) |
| `/supervisor` | Superviseur (multiposte) | **Core** (`VITE_CORE_API_URL`) |
| `/ai-leader` | AI Leader | **Core** |

Stack : Vite, React, TypeScript, Tailwind CSS v4, TanStack Query, react-router, Plotly (`plotly.js-dist-min`, chargé à la demande).

**État : squelette.** Les pages actuelles prouvent le câblage (routing, client API, types, mocks). Le design et les écrans définitifs appartiennent au groupe ARGOS Frontend.

## Démarrer

```powershell
cd frontend
npm ci
npm run dev          # http://127.0.0.1:5173, mode mock par défaut
```

Mode live (Edge réel lancé avec `uvicorn visionhub.argos_app:app --port 8010`) :

```powershell
$env:VITE_API_MODE = "live"; npm run dev
```

Le serveur Vite relaie `/edge-api/*` → `EDGE_PROXY_TARGET` et `/core-api/*` → `CORE_PROXY_TARGET` : aucun réglage CORS n'est nécessaire côté backends. Variables : voir `.env.example` (copier en `.env.local`).

## Organisation

```text
src/
  app/          routing, layout, configuration (variables d'environnement)
  api/          http.ts (client + mode mock), edge.ts, core.ts, hooks.ts (TanStack Query), types.ts
  api/generated GÉNÉRÉ depuis les OpenAPI — ne pas éditer
  mocks/        handlers.ts (routes simulées), fixtures/ GÉNÉRÉES et validées côté Python
  shared/       composants communs (Card, StatTile, VerdictBadge, PlotlyChart…)
  operator/  supervisor/  ai-leader/   un dossier par espace
```

## Contrats

Les types ne sont **jamais** écrits à la main :

```powershell
# à la racine du dépôt, après un changement de contrat Python
.\.venv\Scripts\python.exe -m visionhub.integration.export
cd frontend; npm run gen:api
```

- `openapi/edge.openapi.json` : API Edge réellement implémentée (historique + `/production`).
- `openapi/contracts.openapi.json` : schémas Core, Edge→Core et MLOps (endpoints Core à développer, servis par le mode mock).

## Vérifications

```powershell
npm run typecheck; npm test; npm run build
```
