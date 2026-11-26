// Contrat de données entre le backend et l'interface HOVIS.
// Chaque type correspond à la réponse d'un endpoint décrit dans client.ts.
// Règle RGPD : aucune image de personne n'est envoyée aux écrans superviseur et AI Leader.

export type Role = 'OPERATEUR' | 'SUPERVISEUR' | 'AI_LEADER' | 'ADMIN';

export interface User {
  id: string;
  name: string;
  role: Role; // déduit des droits du compte ; OPERATEUR par défaut
  stationId?: string; // poste rattaché (opérateur)
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
  takenAt: string; // ISO
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
  stationId: string; // « A1·P06 »
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
}

/* ------------------------------------------------------------------ */
/* Superviseur                                                         */
/* ------------------------------------------------------------------ */

export type StationStatus = 'OK' | 'SECURITE' | 'QUALITE' | 'RYTHME' | 'CAMERA' | 'OBJET';

export interface StationSummary {
  id: string; // « A1·P06 »
  deltaVsExpected: number; // pièces d'avance (>0) ou de retard (<0)
  status: StationStatus;
}

export interface CellSummary {
  id: string; // « A1 »
  good: number; // pièces bonnes du shift en cours
  target: number; // objectif du shift
  expectedNow: number;
  ko: number;
  stations: StationSummary[];
  hourly: { hour: number; good: number | null; ko: number }[];
}

export interface LineSummary {
  id: string; // « A »
  name: string; // « Ligne A »
  cells: CellSummary[];
  /** Pièces bonnes des shifts terminés de la journée. */
  finishedShifts: { code: ShiftCode; good: number; target: number }[];
  cameras: { front: [number, number]; part: [number, number] }; // [actives, installées]
}

export type AlertCategory = 'SECURITE_EPI' | 'POSTE' | 'QUALITE' | 'RYTHME' | 'EQUIPEMENT';
export type AlertAction = 'NONE' | 'VALIDATE' | 'MAINTENANCE';

export interface Alert {
  id: string;
  lineId: string;
  stationId: string;
  category: AlertCategory;
  title: string;
  detail: string;
  shift: ShiftCode;
  when: string; // texte lisible : « 16:38, 16:41 et 16:51 » ou « depuis 15 h »
  priority: boolean;
  action: AlertAction; // NONE pour EPI et poste : information seule
  reportedByOperator?: boolean;
}

export interface WorkshopOverview {
  date: string;
  currentShift: Shift;
  dayTarget: number;
  lines: LineSummary[];
  koDay: number;
  koByShift: Partial<Record<ShiftCode, number>>;
  problemsByLine: Record<string, Record<AlertCategory, number>>; // shift en cours
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
}

/* ------------------------------------------------------------------ */
/* AI Leader                                                           */
/* ------------------------------------------------------------------ */

export interface ModelInfo {
  id: string;
  name: string;
  useCase: 'Qualité' | 'EPI' | 'Comportement' | 'Poste';
  scope: string; // « Ligne A », « Poste A1·P06 »
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
  | 'VOIR_COCKPIT' // vue atelier, lignes, cellules
  | 'TRAITER_ALERTES' // valider, rejeter, appeler la maintenance
  | 'GERER_MODELES' // entraîner, déployer, réentraîner
  | 'GERER_ACCES'; // utilisateurs et rôles

export interface AppUser {
  id: string;
  name: string;
  login: string; // identifiant ou e-mail
  badge?: string; // n° de badge pour la connexion au poste
  role: Role;
  scope: string; // périmètre : « Poste A1·P06 », « Lignes A et B », « Usine »
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
  action: string; // « a donné le rôle Superviseur à … »
}
