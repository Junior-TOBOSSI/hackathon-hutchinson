Lis d'abord `AGENTS.md` à la racine du dépôt (et celui du dossier `usecases/<cas>/` concerné). Règles intouchables :

1. Ne jamais modifier `visionhub/contracts.py`, `decision.py`, `registry.py` ni `api.py` sans accord de l'équipe : proposer, puis s'arrêter.
2. Travailler uniquement dans le dossier du cas d'usage concerné (`usecases/<cas>/`).
3. Le test de contrat (`pytest tests/test_contract.py`) doit passer avant toute pull request.
4. Ne jamais versionner de données, d'images ni de poids de modèles ; aucune donnée vers un service externe.
5. Ne jamais stocker ni afficher de visage, ni identifier une personne.
6. Importer les bibliothèques lourdes (ultralytics, anomalib, torch) dans `load()`, pas en haut du module.
7. Code en anglais, réponses en français ; changements petits et expliqués.
