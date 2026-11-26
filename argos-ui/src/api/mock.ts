// Données de démonstration, identiques aux maquettes.
// À supprimer quand le backend répond : client.ts bascule automatiquement (voir USE_MOCK).
import type {
  AiOverview, Alert, AppUser, AuditEntry, LineSummary, RoleDefinition, StationDetail,
  StationIssue, StationLive, User, WorkshopOverview,
} from './types';

export type Scenario = 'ok' | 'ko' | 'epi' | 'multi';

export const mockUsers: Record<string, User> = {
  'm.rojas@hutchinson.com': { id: 'u1', name: 'M. Rojas', role: 'OPERATEUR', stationId: 'A1·P06' },
  'c.diaz@hutchinson.com': { id: 'u2', name: 'C. Díaz', role: 'SUPERVISEUR' },
  'a.noui@hutchinson.com': { id: 'u3', name: 'A. Noui', role: 'AI_LEADER' },
  'admin@hutchinson.com': { id: 'u4', name: 'Admin usine', role: 'ADMIN' },
};

const shiftB = { code: 'B' as const, start: '13:00', end: '21:00' };

const EPI: StationIssue = { id: 'i1', category: 'SECURITE_EPI', label: 'Lunettes absentes', instruction: 'Mettez vos lunettes', since: '2026-11-26T16:50:56' };
const PHONE: StationIssue = { id: 'i2', category: 'POSTE', label: 'Téléphone sur le poste', instruction: 'Rangez le téléphone', since: '2026-11-26T16:51:00' };

export function mockStationLive(scenario: Scenario): StationLive {
  const ko = scenario === 'ko' || scenario === 'multi';
  const issues = scenario === 'epi' ? [EPI] : scenario === 'multi' ? [EPI, PHONE] : [];
  const good = scenario === 'ok' ? 476 : 483;
  return {
    stationId: 'A1·P06',
    product: 'raccord QC 702',
    shift: shiftB,
    now: scenario === 'ok' ? '2026-11-26T16:42:00' : '2026-11-26T16:51:00',
    part: {
      number: scenario === 'ok' ? 476 : 484,
      verdict: ko ? 'KO' : 'OK',
      jointsDetected: ko ? 2 : 1,
      score: ko ? 0.12 : 0.96,
      imageUrl: ko ? '/img/demo-piece-nok.svg' : '/img/demo-piece-ok.svg',
      takenAt: '2026-11-26T16:51:00',
    },
    counters: { good, ko: ko ? 7 : 6 },
    objective: { shiftTarget: 1000, expectedNow: scenario === 'ok' ? 462 : 481, perHour: 125 },
    hourly: [
      { hour: 13, good: 128 }, { hour: 14, good: 131 }, { hour: 15, good: 124 },
      { hour: 16, good: good - 383 }, { hour: 17, good: null }, { hour: 18, good: null },
      { hour: 19, good: null }, { hour: 20, good: null },
    ],
    issues,
    frontSnapshotUrl: scenario === 'multi' ? '/img/demo-camera-multi.svg' : scenario === 'epi' ? '/img/demo-camera-epi.svg' : undefined,
    checks: { securite: !issues.some((i) => i.category === 'SECURITE_EPI'), poste: !issues.some((i) => i.category === 'POSTE'), qualite: true, koRatePct: ko ? 1.4 : 1.2 },
    qualityModelVersion: 'v1.3',
    partCameraOnline: true,
  };
}

const h = (base: number, ko: number) => [
  { hour: 13, good: 752 + (base % 7), ko: 9 }, { hour: 14, good: 741 + base, ko: 14 },
  { hour: 15, good: 733 + Math.round(base / 2), ko: 17 }, { hour: 16, good: 546, ko: Math.max(4, Math.round(ko / 4)) },
  { hour: 17, good: null, ko: 0 }, { hour: 18, good: null, ko: 0 }, { hour: 19, good: null, ko: 0 }, { hour: 20, good: null, ko: 0 },
];
type St = 'OK' | 'SECURITE' | 'QUALITE' | 'RYTHME' | 'CAMERA' | 'OBJET';
const cell = (id: string, statuses: St[], deltas: number[], ko: number) => {
  const delta = deltas.reduce((a, b) => a + b, 0);
  return {
    id, good: 2772 + delta, target: 6000, expectedNow: 2772, ko,
    stations: deltas.map((d, i) => ({ id: `${id}·P0${i + 1}`, deltaVsExpected: d, status: statuses[i] })),
    hourly: h(delta, ko),
  };
};
const O: St = 'OK';
const lines: LineSummary[] = [
  { id: 'A', name: 'Ligne A', finishedShifts: [{ code: 'A', good: 11820, target: 12000 }], cameras: { front: [12, 12], part: [11, 12] },
    cells: [cell('A1', [O, O, 'QUALITE', O, O, 'SECURITE'], [6, 2, -31, -3, 4, -22], 52), cell('A2', [O, 'OBJET', O, 'CAMERA', O, O], [1, 7, 3, 8, 0, 5], 18)] },
  { id: 'B', name: 'Ligne B', finishedShifts: [{ code: 'A', good: 17900, target: 18000 }], cameras: { front: [17, 18], part: [17, 18] },
    cells: [cell('B1', [O, O, O, O, O, O], [2, 4, 1, 6, 3, 2], 15), cell('B2', [O, O, 'RYTHME', O, 'SECURITE', O], [3, -2, -18, 5, -4, 1], 24), cell('B3', [O, 'CAMERA', O, O, O, O], [0, -6, 2, 3, 1, 4], 20)] },
  { id: 'C', name: 'Ligne C', finishedShifts: [{ code: 'A', good: 11930, target: 12000 }], cameras: { front: [12, 12], part: [12, 12] },
    cells: [cell('C1', [O, O, O, O, O, O], [5, 3, 4, 2, 6, 1], 9), cell('C2', [O, O, O, O, O, O], [2, 1, 3, 0, 4, 2], 11)] },
];

export const mockOverview: WorkshopOverview = {
  date: 'Jeudi 26 novembre',
  currentShift: shiftB,
  dayTarget: 126000,
  lines,
  koDay: 439,
  koByShift: { A: 290, B: 149 },
  problemsByLine: {
    A: { SECURITE_EPI: 5, POSTE: 2, QUALITE: 3, RYTHME: 2, EQUIPEMENT: 1 },
    B: { SECURITE_EPI: 3, POSTE: 2, QUALITE: 1, RYTHME: 2, EQUIPEMENT: 2 },
    C: { SECURITE_EPI: 1, POSTE: 1, QUALITE: 1, RYTHME: 0, EQUIPEMENT: 0 },
  },
};

export const mockAlerts: Alert[] = [
  { id: 'a1', lineId: 'A', stationId: 'A1·P06', category: 'SECURITE_EPI', title: 'Lunettes absentes · main près de la presse', detail: 'EPI : lunettes de sécurité non portées (2 fois) · comportement : main dans la zone de la presse (1 fois)', shift: 'B', when: '16:38, 16:41 et 16:51', priority: true, action: 'NONE' },
  { id: 'a2', lineId: 'B', stationId: 'B2·P05', category: 'SECURITE_EPI', title: 'Flaque d’huile près de la presse', detail: 'Signalé par l’opérateur avec le bouton Signaler', shift: 'B', when: '16:40', priority: true, action: 'MAINTENANCE', reportedByOperator: true },
  { id: 'a3', lineId: 'A', stationId: 'A2·P02', category: 'POSTE', title: 'Téléphone posé sur le poste', detail: 'Poste de travail : objet étranger dans la zone de travail', shift: 'B', when: '16:37 · rangé après 40 s', priority: false, action: 'NONE' },
  { id: 'a4', lineId: 'A', stationId: 'A1·P03', category: 'QUALITE', title: '41 KO depuis 13 h', detail: 'Surtout des joints absents : réglage machine à vérifier', shift: 'B', when: 'depuis 13 h', priority: false, action: 'VALIDATE' },
  { id: 'a5', lineId: 'B', stationId: 'B2·P03', category: 'RYTHME', title: 'Retard de 18 pièces', detail: 'Rythme 129 / h depuis 15 h (objectif 143 / h)', shift: 'B', when: 'depuis 15 h', priority: false, action: 'VALIDATE' },
  { id: 'a6', lineId: 'A', stationId: 'A2·P04', category: 'EQUIPEMENT', title: 'Caméra pièce hors ligne', detail: 'Le poste tourne sans contrôle qualité automatique', shift: 'B', when: 'depuis 16:07', priority: false, action: 'MAINTENANCE' },
  { id: 'a7', lineId: 'B', stationId: 'B3·P02', category: 'EQUIPEMENT', title: 'Caméras frontale et pièce hors ligne', detail: 'Mini-PC injoignable', shift: 'B', when: 'depuis 16:30', priority: false, action: 'MAINTENANCE' },
];

const ep = (h1: number, m1: number, h2: number, m2: number): [number, number] => [(h1 - 13) * 60 + m1, (h2 - 13) * 60 + m2];
export const mockStationDetail: StationDetail = {
  stationId: 'A1·P06', product: 'Presse injection · raccord QC 702',
  efficiencyPct: 94.6, good: 382, expectedNow: 404, delta: -22, ratePerHour: 129,
  ko: 9, koRatePct: 2.3, koByDefect: { absent: 6, double: 3 },
  lanes: [
    { name: 'Sécurité', episodes: [ep(14, 12, 14, 14), ep(16, 38, 16, 40), ep(16, 41, 16, 42)] },
    { name: 'Poste', episodes: [ep(16, 37, 16, 40)] },
    { name: 'Qualité', episodes: [ep(15, 5, 15, 7), ep(15, 40, 15, 42), ep(16, 20, 16, 22)] },
    { name: 'Rythme', episodes: [ep(15, 0, 16, 42)], soft: true },
  ],
  epiCounts: [
    { label: 'Lunettes absentes', count: 2 }, { label: 'Gants absents', count: 1 }, { label: 'Casque absent', count: 0 },
    { label: 'Chaussures de sécurité', count: 0 }, { label: 'Téléphone à la main', count: 0 },
    { label: 'Main près de la presse', count: 1 }, { label: 'Zone interdite', count: 0 },
  ],
  events: [
    { time: '16:51', category: 'EPI', label: 'Lunettes de sécurité non portées', detail: 'revenu au vert après 12 s', shift: 'B' },
    { time: '16:41', category: 'COMPORTEMENT', label: 'Main dans la zone de la presse', detail: 'détection 0,82', shift: 'B' },
    { time: '16:38', category: 'EPI', label: 'Lunettes de sécurité non portées', detail: 'revenu au vert après 1 min 50', shift: 'B' },
    { time: '16:37', category: 'POSTE', label: 'Clé de réglage absente de son emplacement', detail: 'remise en place après 3 min', shift: 'B' },
    { time: '14:12', category: 'EPI', label: 'Gants non portés', detail: 'revenu au vert après 25 s', shift: 'B' },
  ],
};

export const mockAi: AiOverview = {
  threshold: 85,
  counts: { healthy: 139, watch: 8, retrain: 3 },
  series: [
    { name: 'Qualité QC 702 · A1·P06', color: '#3D5A8A', values: [95, 95, 94, 95, 94, 93, 93, 92, 90, 89, 87, 85, 83, 81] },
    { name: 'EPI · ligne A', color: '#0B1F3F', values: [93, 92, 93, 92, 91, 91, 90, 88, 87, 85, 83, 81, 80, 78] },
    { name: 'Téléphone · usine', color: '#9AAED0', values: [92, 92, 91, 92, 91, 90, 91, 90, 89, 89, 88, 89, 88, 88] },
  ],
  drifts: [
    { modelId: 'm2', title: 'Qualité QC 702 · poste A1·P06', detail: 'Santé 81 % (seuil 85 %) · dérive des données : images plus sombres depuis mardi', healthPct: 81, mode: 'MANUEL' },
    { modelId: 'm1', title: 'EPI · ligne A (12 postes)', detail: 'Santé 78 % · dérive de concept : nouveaux gants bleus. Auto planifié cette nuit à 2 h.', healthPct: 78, mode: 'AUTO', scheduledAt: '02:00' },
  ],
  models: [
    { id: 'm1', name: 'EPI casque-gants-lunettes', useCase: 'EPI', scope: 'Ligne A', version: 'v2.0', healthPct: 78 },
    { id: 'm2', name: 'Qualité QC 702', useCase: 'Qualité', scope: 'Poste A1·P06', version: 'v1.3', healthPct: 81, recallKoPct: 93 },
    { id: 'm3', name: 'Téléphone à la main', useCase: 'Comportement', scope: 'Toute l’usine', version: 'v1.1', healthPct: 88 },
    { id: 'm4', name: 'Zones poste rangé', useCase: 'Poste', scope: 'Lignes A, B, C', version: 'v1.0', healthPct: 94 },
    { id: 'm5', name: 'Qualité QC 702', useCase: 'Qualité', scope: 'Lignes B et C', version: 'v1.3', healthPct: 95, recallKoPct: 95 },
  ],
  training: { modelName: 'Qualité QC 702', version: 'v1.4', dataset: 'jeu qc702 v3 · 839 images · 20 séquences · test par séquence entière', step: 3, recallKoPct: 96, previousRecallKoPct: 93, absentStoppedPct: 94, doubleStoppedPct: 100 },
  retrainMode: 'AUTO',
};

export const mockRoles: RoleDefinition[] = [
  { role: 'OPERATEUR', label: 'Opérateur', description: 'Rôle par défaut. Voit uniquement son poste.', permissions: ['VOIR_POSTE', 'SIGNALER'] },
  { role: 'SUPERVISEUR', label: 'Superviseur', description: 'Suit les lignes et traite les alertes de son périmètre.', permissions: ['VOIR_COCKPIT', 'TRAITER_ALERTES'] },
  { role: 'AI_LEADER', label: 'AI Leader', description: 'Gère le cycle de vie des modèles.', permissions: ['VOIR_COCKPIT', 'GERER_MODELES'] },
  { role: 'ADMIN', label: 'Admin', description: 'Gère les comptes, les rôles et les périmètres.', permissions: ['GERER_ACCES'] },
];

export const mockAppUsers: AppUser[] = [
  { id: 'u1', name: 'M. Rojas', login: 'm.rojas@hutchinson.com', badge: '004512', role: 'OPERATEUR', scope: 'Poste A1·P06', active: true, lastLogin: '26/11 13:02' },
  { id: 'u5', name: 'J. Pérez', login: 'j.perez@hutchinson.com', badge: '004518', role: 'OPERATEUR', scope: 'Poste B2·P05', active: true, lastLogin: '26/11 13:05' },
  { id: 'u6', name: 'L. Soto', login: 'l.soto@hutchinson.com', badge: '004533', role: 'OPERATEUR', scope: 'Poste A2·P04', active: false, lastLogin: '19/11 05:01' },
  { id: 'u2', name: 'C. Díaz', login: 'c.diaz@hutchinson.com', role: 'SUPERVISEUR', scope: 'Lignes A, B et C', active: true, lastLogin: '26/11 12:55' },
  { id: 'u3', name: 'A. Noui', login: 'a.noui@hutchinson.com', role: 'AI_LEADER', scope: 'Usine', active: true, lastLogin: '26/11 09:14' },
  { id: 'u4', name: 'Admin usine', login: 'admin@hutchinson.com', role: 'ADMIN', scope: 'Usine', active: true, lastLogin: '26/11 16:02' },
];

export const mockAudit: AuditEntry[] = [
  { at: '26/11 16:02', by: 'Admin usine', action: 'a désactivé le compte de L. Soto' },
  { at: '25/11 10:20', by: 'Admin usine', action: 'a étendu le périmètre de C. Díaz à la ligne C' },
  { at: '24/11 08:47', by: 'Admin usine', action: 'a créé le compte de J. Pérez (Opérateur, poste B2·P05)' },
];
