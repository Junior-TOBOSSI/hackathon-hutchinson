# AGENTS.md — contexte pour les assistants de code

## 1. Le projet
Hackathon ESIGELEC × Hutchinson (« AI & Industrial Vision », ~32 h, 7 personnes).
`visionhub` est une plateforme de vision multi-modèles au poste de production.
Trois cas d'usage : **quality** (pièces non conformes), **workstation** (écarts de configuration du poste), **safety** (EPI manquants, téléphone).

## 2. L'architecture
Chaîne : **source → prétraitement → analyseurs → décision → stockage → API → tableau de bord**.
- `visionhub/sources.py` : sources d'images (synthétique par défaut, dossier, vidéo, webcam).
- `visionhub/preprocess.py` : recadrage sur une zone d'intérêt et `anonymize()` (stub).
- `visionhub/analyzer.py` : interface `Analyzer` ; `visionhub/registry.py` : chargement via `usecases/<cas>/config.yaml`.
- `visionhub/decision.py` : score → `conforme` / `a_verifier` / `anomalie`, avec deux seuils par cas d'usage.
- `visionhub/contracts.py` : **tous les schémas de données**.
- `visionhub/store.py` (SQLite), `visionhub/pipeline.py`, `visionhub/api.py` (FastAPI), `dashboard/app.py` (Streamlit, ne parle qu'à l'API).
- `usecases/{quality,workstation,safety}/` : un dossier par binôme. Détails dans `docs/architecture.md`.
- ARGOS : contrats d'intégration dans `docs/integration-contracts.md`, périmètre de chaque groupe dans `docs/team-workstreams.md`.

## 3. Règles intouchables
- **Ne jamais modifier** `visionhub/contracts.py`, `visionhub/decision.py`, `visionhub/registry.py` ni `visionhub/api.py` sans accord explicite de l'équipe. Si un changement semble nécessaire : le proposer et **s'arrêter**.
- Travailler **uniquement** dans le dossier du cas d'usage concerné (`usecases/<cas>/`).
- Le **test de contrat** (`pytest tests/test_contract.py`) doit passer avant toute pull request.
- **Données et poids versionnés** dans `data/` depuis le 2026-11-27, **avec l'accord de Hutchinson** pour un dépôt public (confirmé par Gilbert TOBOSSI) : poids (`data/models/`) et vidéos (`data/raw/safety/videos/`) passent par **Git LFS** (`.gitattributes`, `git lfs install` une fois par machine). Toute nouvelle donnée client doit avoir le même accord avant d'être poussée. **Aucune autre donnée ne part vers un service externe** (pas d'API cloud, pas de télémétrie), hormis l'espace Databricks de l'équipe utilisé par l'AI leader.
- Ne jamais stocker ni afficher de visage, ni chercher à identifier une personne.

## 4. Travailler avec l'humain
- Proposer un **plan** avant d'écrire du code, et attendre sa validation.
- **Expliquer** chaque choix et chaque bloc de code : l'humain doit pouvoir le défendre devant un jury.
- Préférer des changements **petits et lisibles** à de grosses réécritures.
- En cas de doute sur le besoin métier, **poser la question** plutôt que supposer.
- Répondre en **français** ; le code, les noms et les docstrings restent en **anglais**.

## 5. Commandes utiles
| Action | Avec Docker | Sans Docker (venv activé) |
|---|---|---|
| Installer | `docker compose build` | `pip install -e ".[dashboard,dev]"` |
| Démo | `docker compose up` | `python -m visionhub.demo` |
| Tests | `docker compose run --rm tests` | `pytest` |
| Lint | (inclus dans `tests`) | `ruff check .` puis `ruff format .` |

## 6. Avant une pull request
- Tests verts (`pytest`, dont le test de contrat) et `ruff check .` propre.
- `README.md` du cas d'usage à jour.
- `AGENTS.md` du cas d'usage à jour (décisions prises, questions ouvertes, résultats).
