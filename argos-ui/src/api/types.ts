// Contrat de données entre le backend et l'interface HOVIS.
// Chaque type correspond à la réponse d'un endpoint décrit dans client.ts.
// Règle RGPD : aucune image de personne n'est envoyée aux écrans team leader et AI Leader,
// sauf quand le team leader consulte l'écran d'un poste (même vue que l'opérateur, visage flouté).
//
// Organisation de l'usine : Usine > UAP > Cellule > Postes.
// L'interface ne descend jamais au-dessus de la cellule : un team leader voit les postes de SA cellule.

export type Role = 'OPERATEUR' | 'TEAM_LEADER' | 'AI_LEADER' | 'ADMIN';

export interface User {
  id: string;
  name: string;
  role: Role; // déduit des droits du compte ; OPERATEUR par défaut
  stationId?: string; // poste rattaché (opérateur), ex. « C3·P06 »
  cellId?: string; // cellule rattachée (team leader), ex. « C3 »
}

export type ShiftCode = 'A' | 'B' | 'C';

export interface Shift {
  code: ShiftCode;
  start: string; // "13:00"
  end: string; // "21:00"
}

/* ------------------------------------------------------------------ */
/* Opérateur                                                           */
/* ------------------------------------------------------------------ */

export type Verdict = 'OK' | 'KO' | 'A_VERIFIER';

export interface PartResult {
  number: number; // n° de la pièce dans le shift
  verdict: Verdict;
  jointsDetected: number; // 0, 1 ou 2 (règle : exactement 1 joint = OK)
  score: number; // 0..1
  imageUrl: string; // photo prise au lancement du cycle, avec la zone en défaut dessinée si KO
  /** true : pièce détectée KO, revérifiée par l'opérateur et requalifiée OK (fausse alerte). */
  requalified?: boolean;
  takenAt: string; // ISO
  /** Pièce KO en attente : « Confirmer » (pièce au rebut) ou « Laisser passer » (erreur modèle). */
  awaitingConfirmation?: boolean;
}

/**
 * Vérification de l'espace de travail à la prise de poste (cas d'usage workstation).
 * Faite UNE fois, avant toute activité : tant qu'elle n'est pas validée, l'écran montre
 * la photo du poste à la place de la pièce.
 */
export interface WorkstationStartup {
  phase: 'IDLE' | 'CHECK' | 'VALIDATED' | 'RUNNING'; // IDLE = pas démarré ; RUNNING = activité en cours
  step: number; // photo n° step / steps
  steps: number;
  verdict: Verdict; // verdict de la photo affichée
  findings: string[]; // écarts trouvés (anglais, noms des zones)
  imageUrl: string; // photo du poste avec les zones et les écarts encadrés
  validatedAt: string | null; // ISO, quand le poste a été validé
  section: string; // « Machine cell variant »
}

/** Problème en cours au poste, déjà trié par le backend ou trié côté front (voir priority.ts). */
export type IssueCategory =
  | 'SECURITE_EPI' // casque, lunettes, gants, chaussures
  | 'COMPORTEMENT' // téléphone à la main, main dans la presse, zone interdite
  | 'POSTE' // objet étranger, outil absent ou déplacé (Kaizen)
  | 'QUALITE'
  | 'RYTHME'
  | 'EQUIPEMENT'
  | 'SIGNALEMENT'; // bouton « Signaler » de l'opérateur

export interface StationIssue {
  id: string;
  category: IssueCategory;
  label: string; // « Lunettes absentes »
  instruction: string; // « Mettez vos lunettes »
  since: string; // ISO
}

export interface HourlyCount {
  hour: number; // 13 = tranche 13 h – 14 h
  good: number | null; // null = heure à venir
}

export interface StationLive {
  stationId: string; // « C3·P06 »
  product: string; // « raccord QC 702 »
  shift: Shift;
  now: string; // ISO, heure serveur
  part: PartResult;
  counters: { good: number; ko: number };
  objective: { shiftTarget: number; expectedNow: number; perHour: number };
  hourly: HourlyCount[];
  issues: StationIssue[]; // vide = tout va bien
  /** Image de la caméra frontale (visage flouté) : uniquement pour l'écran du poste. */
  frontSnapshotUrl?: string;
  checks: { securite: boolean; poste: boolean; qualite: boolean; koRatePct: number };
  qualityModelVersion: string;
  partCameraOnline: boolean;
  /** Absent = pas de vérification du poste (données de démonstration). */
  startup?: WorkstationStartup;
}

/* ------------------------------------------------------------------ */
/* Team leader : les postes de sa cellule                              */
/* ------------------------------------------------------------------ */

export type StationStatus = 'OK' | 'SECURITE' | 'QUALITE' | 'RYTHME' | 'CAMERA' | 'OBJET';

/** Un poste de la cellule, vu par le team leader et par l'écran TV. */
export interface StationSummary {
  id: string; // « C3·P06 »
  product: string; // « raccord QC 702 »
  good: number; // pièces bonnes du shift en cours
  target: number; // objectif du shift pour ce poste
  expectedNow: number; // pièces attendues à cette heure-ci
  ko: number;
  status: StationStatus;
}

/** GET /api/cells/{cellId}/overview */
export interface CellOverview {
  uap: { id: string; name: string }; // « UAP2 », « UAP 2 · Injection » (affichage seul)
  cell: { id: string; name: string }; // « C3 », « Cellule 3 »
  date: string; // « Jeudi 26 novembre »
  currentShift: Shift;
  stations: StationSummary[]; // tous les postes de la cellule (12 en général)
  /** Production de la cellule heure par heure (somme des postes). */
  hourly: { hour: number; good: number | null; ko: number }[];
}

export type AlertCategory = 'SECURITE_EPI' | 'POSTE' | 'QUALITE' | 'RYTHME' | 'EQUIPEMENT';
export type AlertAction = 'NONE' | 'VALIDATE' | 'MAINTENANCE';

export interface Alert {
  id: string;
  cellId: string;
  stationId: string;
  category: AlertCategory;
  title: string;
  detail: string;
  shift: ShiftCode;
  when: string; // texte lisible : « 16:38, 16:41 et 16:51 » ou « depuis 15 h »
  priority: boolean;
  action: AlertAction; // NONE pour EPI et poste : information seule
  reportedByOperator?: boolean;
  /** Renseigné quand le team leader a pris l'alerte en charge : qui, et à quelle heure (ISO). */
  acknowledgedBy?: string;
  acknowledgedAt?: string;
}

export interface StationEvent {
  time: string; // « 16:38 »
  category: 'EPI' | 'COMPORTEMENT' | 'POSTE';
  label: string;
  detail: string;
  shift: ShiftCode;
}

export interface StationDetail {
  stationId: string;
  product: string;
  efficiencyPct: number;
  good: number;
  expectedNow: number;
  delta: number;
  ratePerHour: number;
  ko: number;
  koRatePct: number;
  koByDefect: { absent: number; double: number };
  /** Épisodes par catégorie sur le shift : [début, fin] en minutes depuis le début du shift. */
  lanes: { name: string; episodes: [number, number][]; soft?: boolean }[];
  epiCounts: { label: string; count: number }[];
  events: StationEvent[];
  /** Shift affiché (celui en cours) et minutes écoulées depuis son début. Absent : shift B, 282 min (démo). */
  shift?: Shift;
  elapsedMin?: number;
}

/* ------------------------------------------------------------------ */
/* AI Leader                                                           */
/* ------------------------------------------------------------------ */

export interface ModelInfo {
  id: string;
  name: string;
  useCase: 'Qualité' | 'EPI' | 'Comportement' | 'Poste';
  scope: string; // « UAP 2 », « Poste C3·P06 »
  version: string;
  healthPct: number; // part des verdicts confirmés par les opérateurs
  recallKoPct?: number;
}

export interface Drift {
  modelId: string;
  title: string;
  detail: string;
  healthPct: number;
  mode: 'MANUEL' | 'AUTO';
  scheduledAt?: string;
}

export interface TrainingRun {
  modelName: string;
  version: string;
  dataset: string;
  step: 0 | 1 | 2 | 3 | 4 | 5; // Photos, Labels, Entraînement, Test, Registre, Déploiement
  recallKoPct: number;
  previousRecallKoPct: number;
  absentStoppedPct: number;
  doubleStoppedPct: number;
}

export interface AiOverview {
  threshold: number; // 85
  counts: { healthy: number; watch: number; retrain: number };
  series: { name: string; values: number[]; color: string }[]; // santé sur 14 jours
  drifts: Drift[];
  models: ModelInfo[];
  training: TrainingRun;
  retrainMode: 'MANUEL' | 'AUTO';
}

/* ------------------------------------------------------------------ */
/* Admin : gestion des accès                                           */
/* ------------------------------------------------------------------ */

export type Permission =
  | 'VOIR_POSTE' // écran du poste
  | 'SIGNALER'
  | 'VOIR_CELLULE' // postes de sa cellule, écran d'un poste en consultation
  | 'TRAITER_ALERTES' // acquitter, valider, rejeter, appeler la maintenance
  | 'GERER_MODELES' // entraîner, déployer, réentraîner
  | 'GERER_ACCES'; // utilisateurs et rôles

export interface AppUser {
  id: string;
  name: string;
  login: string; // identifiant ou e-mail
  badge?: string; // n° de badge pour la connexion au poste
  role: Role;
  scope: string; // périmètre : « Poste C3·P06 », « Cellule 3 · UAP 2 », « Usine »
  active: boolean;
  lastLogin?: string;
}

export interface RoleDefinition {
  role: Role;
  label: string;
  description: string;
  permissions: Permission[];
}

export interface AuditEntry {
  at: string; // « 26/11 16:02 »
  by: string;
  action: string; // « a donné le rôle Team leader à … »
}
