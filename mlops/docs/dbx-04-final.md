# DBX-04-FINAL — Finitions Datasets et préparation de presse-5s

Base : `c90cd8e` (catalogue indépendant, Codex), sur la branche `feat/datasets-catalog`. Le backend du catalogue n'est pas modifié.

## Interface

- **Largeur** :
  - conteneur AI Leader élargi à 2 400 px, avec des marges adaptatives ;
  - catalogue en pleine largeur sans sélection ;
  - catalogue et détail répartis à 38/62 quand un dataset est ouvert, avec un catalogue compact (colonnes secondaires masquées) ;
  - sous 1 100 px, le détail occupe toute la largeur.
- **Kit partagé** `pages/ai-leader/ui.tsx` et `ui.css`, réutilisable par Training Factory :
  - `Kpi` : icône HOVIS dans un carré bleu clair ;
  - `SearchField` et `SelectField` : apparence harmonisée, icônes de recherche, de filtre et de tri ;
  - `Chip` ;
  - `Donut` : générique, couleurs fournies par l'appelant, total au centre, légende avec effectifs et pourcentages, infobulle ;
  - `StackedBar` : trois bleus pour train, validation et test ;
  - `fr()` : libellés français ;
  - `classColor()` : OK et good en vert, NOK en rouge, types NOK en nuances distinctes, autres classes sur une palette stable.
- **Splits** : barre empilée unique, et tableau « Classes par split » compact (sans largeur minimale, avec une colonne Total) : plus de débordement.
- **Versions** : indicateurs sélectionnée, dernière publiée, version initiale, utilisée / non utilisée, brouillon. Modifications affichées en pastilles : validées, corrigées, exclues, importées. Comparaison qui indique si les évaluations sont comparables.
- **Galerie** : vignettes de 160 px et filtres harmonisés ; chargement différé et routes sécurisées inchangés.

## presse-5s (préparation locale uniquement)

`python -m mlops.datasets_prep.presse_5s prepare --zip presse_5S_20.zip`

- **Contenu** : 20 images PNG de 496×325 px.
  - Les classes réelles sont dans `labels.csv` : good 5, disorder 7, zone_object 4, zone_person 4. Les dossiers ne distinguent que `good` et `anomaly`.
  - `reference.png` est identique, octet pour octet, à `good/good_001.png` : il est exclu et ne compte pas comme échantillon.
- **Deux sources** :
  - 6 images d'un « lot pilote validé » ;
  - 14 recadrages d'**une seule planche générée**, quasi identiques entre eux (empreinte perceptuelle : distance de 2 à 5 sur 256).
- **Découpage par source** : la planche entière va en **train** (12 images), le lot pilote indépendant en **test** (6 images ; les 4 classes y sont présentes). Il n'y a **pas de split de validation** : 20 images ne le permettent pas sans fuite.
- **Sorties**, dans `<ARGOS_MLOPS_HOME>/prep/presse-5s/v1/` (hors dépôt) : images copiées sans aucune modification, `plan.json` (empreintes SHA-256, sources, notes) et `REVIEW.md` (liste de revue humaine).
- **Import** : la commande `import` rejoue le plan via l'API de Codex (création de la famille, premier brouillon, imports par classe et par split, publication de `v1`). Elle est **refusée sans** `--i-have-explicit-authorization`.

**Limite** : l'import de Codex n'enregistre pas la source dans les éléments du manifeste. Elle reste traçable par le nom d'origine (`origin.import`) et par `plan.json`.
