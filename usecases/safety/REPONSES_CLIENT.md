# Cas d'usage Safety : réponses aux questions du client

> Questions qu'un responsable sécurité ou production de Hutchinson est susceptible de poser sur le prototype de détection des EPI, et nos réponses.
> Les chiffres viennent de nos mesures (validation SH17, 810 images). Les lignes marquées **[à compléter]** attendent les résultats du jeu de test (810 images jamais utilisées) ou d'un test sur site.

## Rappel du contexte

- **Demande du client** : faute d'images de l'usine, le prototype a été entraîné sur un jeu de données public (SH17, photos industrielles issues de Pexels), à la demande de Hutchinson.
- **Le prototype démontre la chaîne complète** : caméra, détection des EPI, logique de décision, alerte sur le tableau de bord, en temps réel et hors ligne.
- **En production**, le modèle serait réentraîné sur des images des postes Hutchinson. C'est la suite naturelle du projet : elle répond à plusieurs des questions ci-dessous.

| Élément | Choix actuel |
|---|---|
| EPI obligatoires | casque, lunettes, gants, chaussures de sécurité ; téléphone interdit |
| Modèle | YOLOv8s entraîné sur 9 classes (11,1 M paramètres), repli YOLOv8n (3,1 M) |
| Score moyen (mAP50, validation) | 0,68 (YOLOv8s), 0,63 (YOLOv8n) |
| Temps d'analyse | ~80 ms par image sur un ordinateur portable, téléphone compris |
| Vie privée | visages pixellisés, aucune image enregistrée, fonctionnement 100 % local |

---

## 1. « Combien de fausses alertes par heure, sur notre atelier ? »

**Réponse courte : pas encore mesuré sur votre atelier, et c'est la première chose que mesurera le pilote.**

- **Ce que l'on sait** : sur une image isolée, le modèle ne voit pas environ un EPI sur deux à deux sur cinq (rappel de 0,45 à 0,60 selon l'EPI). Sans protection, cela produirait des fausses alertes du type « lunettes absentes » alors que la personne les porte.
- **Ce qui limite déjà ces fausses alertes** :
  - **la règle de preuve** : un EPI n'est déclaré absent que si la partie du corps qu'il protège est visible (main nue, tête, visage). Une main cachée donne « non vérifié », jamais une alerte ;
  - **le lissage** : une alerte demande que le problème soit vu sur 3 images de suite (1,5 s). Une erreur isolée ne déclenche rien ;
  - **deux niveaux d'alerte** : une preuve faible donne « à vérifier » (orange), seule une preuve nette donne « anomalie » (rouge).
- **Comment nous le mesurerons** : une vidéo d'un opérateur équipé de tous ses EPI pendant une durée fixe ; toute alerte est alors une fausse alerte. Résultat exprimé en **fausses alertes par heure et par poste**. **[à compléter]**
- **Leviers si le taux est trop élevé**, sans réentraîner : recadrer l'image sur la zone du poste (les EPI deviennent plus gros), allonger le lissage (5 images = 2,5 s), ajuster les seuils de confiance par EPI. Avec réentraînement : **les images de votre atelier**, qui sont le levier le plus fort.

## 2. « Vous détectez *nos* chaussures de sécurité, ou n'importe quelles chaussures ? »

**Réponse courte : aujourd'hui n'importe quelles chaussures et n'importe quels gants ; distinguer vos EPI demande vos images, et c'est prévu.**

- Le jeu public SH17 ne fait pas la différence entre chaussures de sécurité et baskets, ni entre gants anti-coupure et gants ordinaires. Aucun modèle entraîné dessus ne peut donc la faire.
- **Solution prévue, en deux étapes** :
  1. le détecteur actuel trouve la chaussure (ou le gant) ;
  2. un petit **classifieur** regarde le gros plan et répond « chaussure de sécurité » ou « non ».
- **Avantage** : pas besoin de réentraîner le détecteur. Le classifieur s'entraîne en quelques minutes sur quelques centaines de photos de **vos** EPI, portés et non portés.
- Lors du réentraînement sur les données de l'usine, on peut aussi ajouter directement des classes « chaussures de sécurité », « gants anti-coupure », etc.

## 3. « Pouvons-nous l'utiliser en production ? »

**Réponse courte : oui après réentraînement sur vos données, avec deux points de licence à régler.**

- **Les données** : SH17 est sous licence non commerciale (CC BY-NC-SA 4.0). Elle convient au prototype, demandé sur données publiques. **En production, le modèle sera réentraîné sur les images de l'usine**, ce qui lève cette contrainte et améliore la précision sur vos postes, vos EPI et votre éclairage.
- **Le logiciel** : la bibliothèque YOLO d'Ultralytics est sous licence **AGPL-3.0**. Pour un usage industriel interne et non diffusé, il faut faire valider la conformité par votre service juridique. Sinon, deux options : une **licence Enterprise Ultralytics**, ou un modèle de détection sous licence permissive (Apache 2.0, par exemple YOLOX). **[à valider avec Hutchinson]**
- **Le reste de la chaîne** (logique de décision, plateforme, tableau de bord) est indépendant du modèle : changer de modèle ne demande qu'une ligne de configuration.

## 4. « Ça tient sur un Raspberry Pi ? Quelle caméra ? »

**Réponse courte : vraisemblablement oui sur Raspberry Pi 5 ; à mesurer sur le boîtier retenu.**

- **Mesuré** : ~80 ms par image sur un ordinateur portable (modèle EPI YOLOv8s + modèle téléphone).
- **Estimé sur Raspberry Pi 5** (format NCNN, à mesurer) : YOLOv8n ~150 à 400 ms par image, YOLOv8s ~300 à 800 ms. Un Raspberry Pi 4 est 2 à 3 fois plus lent.
- **Recommandation matérielle** :

| Configuration | Modèle | Cadence |
|---|---|---|
| Raspberry Pi 5 + refroidissement actif | YOLOv8s à 1 image/s, ou YOLOv8n à 2 images/s | suffisante pour des EPI |
| Raspberry Pi 5 + accélérateur IA (Hailo) | YOLOv8s | 2 images/s ou plus |
| Raspberry Pi 4 | YOLOv8n | ~1 image/s |

- **Délai d'alerte** : environ 1,5 à 3 s (cadence + lissage sur 3 images). Le temps du modèle n'en représente qu'une petite partie.
- **Caméra recommandée** :

| Critère | Recommandation |
|---|---|
| Résolution | 1080p |
| Champ de vision | grand angle (90 à 120°) : l'opérateur doit être visible en entier, pieds compris |
| Position | en hauteur (2,2 à 2,5 m), inclinée vers le bas, face à l'opérateur, à 2 à 4 m |
| Éclairage | exposition fixe, éviter les contre-jours |
| Protection | boîtier IP65 ou plus |
| Connexion | caméra branchée directement au boîtier (module caméra Raspberry Pi ou USB) : pas de réseau, plus simple et plus sûr |

- **Piste d'amélioration** : la génération YOLO26 annonce environ 2 fois plus de vitesse sur processeur que YOLOv8 à taille égale (chiffre du fabricant). Elle sera entraînée avec le même protocole, pour comparaison. **[à compléter]**

## 5. « Et le casque ? Son chiffre est-il fiable ? »

**Réponse courte : c'est le chiffre le moins fiable, faute d'exemples ; les images de l'usine le corrigeront.**

- Le casque est rare dans SH17 : 773 exemples à l'entraînement, **70 en validation**. Son score (0,61 pour YOLOv8s) a donc une forte marge d'incertitude.
- La preuve associée, la tête, est très bien détectée (score 0,89, 86 % des têtes trouvées) : quand une tête est visible sans casque, l'alerte est fiable.
- **Amélioration prévue** : des images de vos opérateurs casqués lors du réentraînement ; mesure sur le jeu de test et sur le site. **[à compléter]**

## 6. « Qui reçoit l'alerte, et que fait-on ensuite ? »

**Réponse courte : le tableau de bord montre l'alerte au responsable ; le processus d'usage est à définir avec vous.**

- **Aujourd'hui** : chaque image donne une décision (**conforme**, **à vérifier**, **anomalie**) avec le détail par personne (« casque absent, gants non vérifiés, téléphone »). Le tableau de bord affiche le flux des événements, les compteurs, et une **file de revue** où un responsable confirme ou infirme chaque alerte.
- **Ces confirmations servent deux fois** : elles mesurent le vrai taux de fausses alertes, et elles signalent les images à ajouter au prochain réentraînement.
- **Proposition de processus** :
  1. « anomalie » : notification au chef d'équipe, rappel des consignes à l'opérateur ;
  2. « à vérifier » : vérification visuelle quand c'est possible ;
  3. bilan hebdomadaire par poste, **sans suivi individuel des personnes**.
- **Cadre RGPD** : finalité de prévention, pas de sanction automatique ; information des salariés et des représentants du personnel ; aucune image conservée ; le système ne cherche jamais à identifier une personne.

---

## Proposition : un pilote d'un poste

| Étape | Contenu | Durée indicative |
|---|---|---|
| 1. Installation | caméra et boîtier sur un poste, zone d'intérêt réglée | 1 jour |
| 2. Collecte | 500 à 1 000 images du poste, avec et sans EPI, annotées | 1 semaine |
| 3. Réentraînement | modèle entraîné sur les images de l'usine, comparé au prototype sur le même test | 1 à 2 jours |
| 4. Mesure en conditions réelles | fausses alertes, absences détectées, délai, cadence | 1 semaine |

**Objectifs proposés pour valider le pilote** (à ajuster avec Hutchinson) :

| Indicateur | Objectif |
|---|---|
| Absences d'EPI détectées | ≥ 90 %, en moins de 5 s |
| Fausses alertes | < 1 par heure et par poste |
| Cadence sur le boîtier | ≥ 1 image par seconde |
| Vie privée | aucun visage visible, aucune image conservée |
