# ARGOS : interface utilisateur

Front-end de la solution ARGOS (hackathon Hutchinson × ESIGELEC, sujet 3 « AI & Industrial Vision »).
React 18 + TypeScript + Vite, sans librairie de composants ni de graphiques : tout est dans `src/`.

## Lancer

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # version de production dans dist/
```

Par défaut l'interface tourne sur des **données de démonstration** (`src/api/mock.ts`).
Pour la brancher sur le backend :

```bash
VITE_USE_MOCK=false VITE_API_URL=http://localhost:8000/api npm run dev
```

En dev, `/api` est aussi redirigé vers `http://localhost:8000` (voir `vite.config.ts`).

## Comptes de démonstration

Le rôle vient des droits du compte. Sans rôle attribué, c'est **opérateur**.

| Identifiant | Rôle | Page d'arrivée |
|---|---|---|
| `m.rojas@hutchinson.com` | Opérateur | `/operateur` |
| `c.diaz@hutchinson.com` | Superviseur | `/superviseur` |
| `a.noui@hutchinson.com` | AI Leader | `/ai-leader` |
| `admin@hutchinson.com` | Admin | `/admin` |

N'importe quel autre identifiant ouvre l'écran opérateur. Le mot de passe n'est pas vérifié en démo.

## Écrans et routes

| Route | Persona | Contenu |
|---|---|---|
| `/` | tous | Connexion (identifiant / mot de passe, ou badge au poste) |
| `/operateur` | Opérateur | Écran du poste. Un seul écran qui s'adapte : tout va bien, pièce KO, EPI ou poste en défaut, plusieurs problèmes. En démo : `?scenario=ok\|ko\|epi\|multi` ou le sélecteur en bas de l'écran |
| `/cellule` | écran mural | 4 voyants lisibles de loin |
| `/superviseur` | Superviseur | Onglets : vue d'ensemble (objectif de la journée), production (ligne > cellules > postes), alertes, équipements. S'adapte au téléphone (onglets en bas) |
| `/superviseur/poste/:id` | Superviseur | Détail d'un poste |
| `/ai-leader` | AI Leader | Santé des modèles, dérives, réentraînement manuel ou auto, versions, entraînement en cours |
| `/admin` | Admin | Utilisateurs (rôle, périmètre, activation), matrice des droits, journal |

Les routes sont protégées par rôle dans `src/App.tsx` (`Guard`).

## Règles à respecter côté backend

1. **Aucune image de personne** n'est envoyée aux écrans superviseur et AI Leader. Les alertes sont du texte : poste, catégorie, description, shift, heure.
2. L'image de la caméra frontale (`frontSnapshotUrl`, visage flouté) ne sert qu'à l'écran du poste et ne doit pas être conservée.
3. **Une alerte = un épisode par poste**, jamais en double (le backend regroupe).
4. Les alertes **EPI et poste** sont informatives : `action: 'NONE'`, sans validation. Qualité et rythme : `VALIDATE`. Équipement et signalements : `MAINTENANCE`.
5. Les indicateurs portent sur le **poste**, jamais sur la personne (aucun nom, aucun classement d'opérateurs).
6. La règle de priorité affichée à l'opérateur quand plusieurs problèmes arrivent en même temps est dans `src/components/priority.ts` : sécurité, puis pièce KO, puis poste de travail.

## Contrat d'API

Tous les types sont dans `src/api/types.ts`. Tous les appels passent par `src/api/client.ts`, qui documente chaque endpoint.

| Méthode | Endpoint | Réponse |
|---|---|---|
| POST | `/api/auth/login` `{login, password}` ou `{badge}` | `User` |
| GET | `/api/stations/{id}/live` | `StationLive` |
| POST | `/api/stations/{id}/report` | 204 (bouton Signaler) |
| GET | `/api/workshop/overview` | `WorkshopOverview` |
| GET | `/api/alerts?status=open` | `Alert[]` |
| POST | `/api/alerts/{id}/decision` `{decision: 'VALIDER'\|'REJETER'}` | 204 |
| POST | `/api/alerts/{id}/maintenance` | 204 |
| GET | `/api/stations/{id}/detail` | `StationDetail` |
| GET | `/api/models/overview` | `AiOverview` |
| POST | `/api/models/{id}/retrain` | 202 |
| PUT | `/api/models/retrain-mode` `{mode}` | 204 |
| POST | `/api/models/{id}/promote` `{version}` | 204 |
| GET | `/api/admin/users` | `AppUser[]` |
| POST | `/api/admin/users` | `AppUser` |
| PATCH | `/api/admin/users/{id}` `{role?, scope?, active?}` | `AppUser` |
| GET | `/api/admin/roles` | `RoleDefinition[]` |
| GET | `/api/admin/audit` | `AuditEntry[]` |

**Temps réel :** l'interface interroge le backend à intervalle régulier (`useApi`, 2 s au poste, 5 s pour les alertes).
Si vous exposez des WebSockets (`/api/ws/stations/{id}`, `/api/ws/alerts`) qui poussent les mêmes objets, il suffit de remplacer le polling dans `src/hooks/useApi.ts`.

**Authentification :** les requêtes partent avec `credentials: 'include'` (cookie de session). Pour un jeton, ajoutez l'en-tête `Authorization` dans `http()` de `client.ts`.

## Structure

```
src/
  api/        types.ts (contrat), client.ts (appels), mock.ts (démo)
  components/ ui.tsx (bandeau, badges, icônes), charts.tsx (anneau, jauges, histogramme, camembert, courbes), priority.ts
  pages/      Login, Operateur, Cellule, Superviseur, PosteDetail, AiLeader, Admin
  theme.css   couleurs et styles communs (bleu, blanc, vert ; rouge pour les alertes)
public/img/   logo ARGOS et images de démonstration
```

## Images de démonstration

`public/img/demo-piece-*.svg` et `demo-camera-*.svg` sont des **dessins**, pas des photos réelles :
les images du jeu qualité 702 ne doivent pas sortir des postes de l'équipe sans accord.
En production, le backend fournit `part.imageUrl` (photo de la pièce avec la zone en défaut dessinée) et `frontSnapshotUrl`.
