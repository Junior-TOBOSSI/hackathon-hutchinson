/* Traduction en français des messages techniques CONNUS renvoyés par le backend
   (en anglais par convention de code). Un message inconnu est affiché tel quel :
   rien n'est inventé ni masqué. */

const RULES: [RegExp, string | ((...m: string[]) => string)][] = [
  [/SQL warehouse is (\w+) and autostart is disabled \(no cost incurred\)/, (_, s) => `SQL warehouse ${s === 'STOPPED' ? 'arrêté' : s} : démarrage automatique désactivé (aucun coût engagé)`],
  [/^Databricks unreachable$/, 'Databricks injoignable'],
  [/Databricks too slow: request time budget exceeded( while waiting for a shared read)?/, 'Databricks trop lent : délai de la requête dépassé'],
  [/^request time budget exceeded/, 'Délai de la requête dépassé'],
  [/^permission denied on (.+)$/, (_, w) => `Permission refusée sur ${w}`],
  [/^unknown model id '(.+)'$/, (_, m) => `Modèle inconnu : ${m}`],
  [/^job '(.+)' already has an active run$/, (_, j) => `Le job « ${j} » a déjà une exécution en cours`],
  [/^job '(.+)' is not triggerable from ARGOS$/, (_, j) => `Le job « ${j} » ne peut pas être lancé depuis ARGOS`],
  [/^alias must be one of/, "L'alias doit être champion ou challenger"],
  [/^no dataset configured for (.+)$/, (_, m) => `Aucun dataset configuré pour ${m}`],
  [/^dataset version (.+) not found$/, (_, v) => `Version de dataset ${v} introuvable`],
  [/^image not listed in this version$/, "Image absente du manifeste de cette version"],
  [/^image not in this draft$/, 'Image absente de ce brouillon'],
  [/^invalid file path$/, 'Chemin de fichier refusé'],
  [/^invalid version name/, 'Nom de version invalide (minuscules, chiffres et tirets, 2 à 41 caractères)'],
  [/^invalid draft id$/, 'Identifiant de brouillon invalide'],
  [/^draft is (\w+): it can no longer be modified$/, (_, s) => `Brouillon ${s === 'published' ? 'déjà publié' : 'en cours de publication'} : il ne peut plus être modifié`],
  [/^draft already published as (.+)$/, (_, v) => `Brouillon déjà publié sous ${v}`],
  [/^draft is being published as (.+)$/, (_, v) => `Ce brouillon est en cours de publication sous ${v}`],
  [/^draft is being published: resume or finish it first$/, 'Brouillon en cours de publication : reprendre ou terminer la publication avant de le supprimer'],
  [/^nothing to publish: the draft has no change$/, 'Rien à publier : le brouillon ne contient aucune modification'],
  [/^version (.+) already exists$/, (_, v) => `La version ${v} existe déjà : une version publiée n'est jamais réécrite`],
  [/^version (.+) is already being published$/, (_, v) => `La version ${v} est déjà en cours de publication`],
  [/^folder (.+) exists without manifest/, (_, v) => `Le dossier ${v} existe sans manifeste (publication interrompue d'un autre brouillon)`],
  [/this version is being published by another process/, 'Cette version est en cours de publication par un autre processus'],
  [/^parent manifest changed since the draft was created$/, 'Le manifeste parent a changé depuis la création du brouillon'],
  [/^file not in the parent version$/, 'Fichier absent de la version parente'],
  [/^label not among the dataset classes$/, "Label absent des classes du dataset"],
  [/^same label as the current one: use validate$/, 'Label identique : utiliser « Valider »'],
  [/^label correction is only supported for classification$/, 'La correction de label ne concerne que la classification'],
  [/^import is only supported for classification datasets$/, "L'import ne concerne que les datasets de classification"],
  [/^synthetic data attestation required$/, 'Attestation « données synthétiques » obligatoire'],
  [/^split must be train, validation or test$/, 'Split invalide'],
  [/^too many files \(max 50\)$/, 'Trop de fichiers (50 au maximum)'],
  [/^file too large \(max 2 MB\)$/, 'Fichier trop volumineux (2 Mo au maximum)'],
  [/^request too large \(max 25 MB\)$/, 'Envoi trop volumineux (25 Mo au maximum)'],
  [/^not a valid image$/, 'Image illisible'],
  [/^format must be PNG or JPEG$/, 'Format refusé (PNG ou JPEG uniquement)'],
  [/^image larger than 4096 px$/, 'Image trop grande (4096 px au maximum)'],
  [/^duplicate image \(same SHA-256\)/, 'Doublon (même empreinte SHA-256 déjà présente)'],
  [/^two items would have the same file path$/, 'Deux éléments auraient le même chemin'],
  [/SHA-256 mismatch after upload/, "Empreinte SHA-256 différente après l'envoi"],
  [/does not match its recorded SHA-256/, 'Fichier source différent de son empreinte enregistrée'],
  [/already exists with other content/, 'Un fichier différent existe déjà à cet emplacement (jamais écrasé)'],
  [/ not found$/, (m) => m.replace(/ not found$/, ' introuvable')],
];

export function translate(message: string): string {
  for (const [re, out] of RULES) {
    const m = message.match(re);
    if (m) return typeof out === 'string' ? message.replace(re, out) : message.replace(re, () => out(...(m as unknown as string[])));
  }
  return message;
}
