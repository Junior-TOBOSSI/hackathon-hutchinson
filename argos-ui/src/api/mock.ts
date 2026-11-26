// Données de démonstration, identiques aux maquettes.
// À supprimer quand le backend répond : client.ts bascule automatiquement (voir USE_MOCK).
import type {
  AiOverview, Alert, AppUser, AuditEntry, CellOverview, RoleDefinition, StationDetail,
  StationIssue, StationLive, StationSummary, User,
} from './types';

export type Scenario = 'ok' | 'ko' | 'epi' | 'multi';

export const mockUsers: Record<string, User> = {
  'm.rojas@hutchinson.com': { id: 'u1', name: 'M. Rojas', role: 'OPERATEUR', stationId: 'C3·P06' },
  'c.diaz@hutchinson.com': { id: 'u2', name: 'C. Díaz', role: 'TEAM_LEADER', cellId: 'C3' },
  'a.noui@hutchinson.com': { id: 'u3', name: 'A. Noui', role: 'AI_LEADER' },
  'admin@hutchinson.com': { id: 'u4', name: 'Admin usine', role: 'ADMIN' },
};

const shiftB = { code: 'B' as const, start: '13:00', end: '21:00' };

const EPI: StationIssue = { id: 'i1', category: 'SECURITE_EPI', label: 'Lunettes absentes', instruction: 'Mettez vos lunettes', since: '2026-11-26T16:50:56' };
const PHONE: StationIssue = { id: 'i2', category: 'POSTE', label: 'Téléphone sur le poste', instruction: 'Rangez le téléphone', since: '2026-11-26T16:51:00' };

/** Écran d'un poste. Les compteurs reprennent ceux du poste dans la cellule (mockCell). */
export function mockStationLive(scenario: Scenario, stationId = 'C3·P06'): StationLive {
  const ko = scenario === 'ko' || scenario === 'multi';
  const issues = scenario === 'epi' ? [EPI] : scenario === 'multi' ? [EPI, PHONE] : [];
  const base = stations.find((st) => st.id === stationId) ?? stations[5];
  const good = base.good;
  return {
    stationId,
    product: 'raccord QC 702',
    shift: shiftB,
    now: '2026-11-26T16:51:00',
    part: {
      number: good + base.ko + 1,
      verdict: ko ? 'KO' : 'OK',
      jointsDetected: ko ? 2 : 1,
      score: ko ? 0.12 : 0.96,
      imageUrl: ko ? '/img/demo-piece-nok.svg' : '/img/demo-piece-ok.svg',
      takenAt: '2026-11-26T16:51:00',
    },
    counters: { good, ko: base.ko + (ko ? 1 : 0) },
    objective: { shiftTarget: 1000, expectedNow: base.expectedNow, perHour: 125 },
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

/* Cellule 3 de l'UAP 2 : 12 postes. Objectif 1 000 pièces par poste et par shift (125 / h). */
type St = StationSummary['status'];
const station = (n: number, good: number, ko: number, status: St): StationSummary => ({
  id: `C3·P${String(n).padStart(2, '0')}`, product: 'raccord QC 702', good, target: 1000, expectedNow: 462, ko, status,
});
const stations: StationSummary[] = [
  station(1, 470, 4, 'OK'), station(2, 468, 3, 'OK'), station(3, 431, 41, 'QUALITE'), station(4, 455, 6, 'CAMERA'),
  station(5, 459, 5, 'SECURITE'), station(6, 476, 6, 'SECURITE'), station(7, 444, 7, 'RYTHME'), station(8, 466, 2, 'OK'),
  station(9, 463, 4, 'OBJET'), station(10, 472, 3, 'OK'), station(11, 465, 5, 'OK'), station(12, 469, 2, 'OK'),
];
const cellGood = stations.reduce((sum, st) => sum + st.good, 0);

export const mockCell: CellOverview = {
  uap: { id: 'UAP2', name: 'UAP 2 · Injection' },
  cell: { id: 'C3', name: 'Cellule 3' },
  date: 'Jeudi 26 novembre',
  currentShift: shiftB,
  stations,
  hourly: [
    { hour: 13, good: 1490, ko: 24 }, { hour: 14, good: 1512, ko: 31 }, { hour: 15, good: 1478, ko: 22 },
    { hour: 16, good: cellGood - 1490 - 1512 - 1478, ko: 11 },
    { hour: 17, good: null, ko: 0 }, { hour: 18, good: null, ko: 0 }, { hour: 19, good: null, ko: 0 }, { hour: 20, good: null, ko: 0 },
  ],
};

export const mockAlerts: Alert[] = [
  { id: 'a1', cellId: 'C3', stationId: 'C3·P06', category: 'SECURITE_EPI', title: 'Lunettes absentes · main près de la presse', detail: 'EPI : lunettes de sécurité non portées (2 fois) · comportement : main dans la zone de la presse (1 fois)', shift: 'B', when: '16:38, 16:41 et 16:51', priority: true, action: 'NONE' },
  { id: 'a2', cellId: 'C3', stationId: 'C3·P05', category: 'SECURITE_EPI', title: 'Flaque d’huile près de la presse', detail: 'Signalé par l’opérateur avec le bouton Signaler', shift: 'B', when: '16:40', priority: true, action: 'MAINTENANCE', reportedByOperator: true },
  { id: 'a3', cellId: 'C3', stationId: 'C3·P09', category: 'POSTE', title: 'Téléphone posé sur le poste', detail: 'Poste de travail : objet étranger dans la zone de travail', shift: 'B', when: '16:37 · rangé après 40 s', priority: false, action: 'NONE' },
  { id: 'a4', cellId: 'C3', stationId: 'C3·P03', category: 'QUALITE', title: '41 KO depuis 13 h', detail: 'Surtout des joints absents : réglage machine à vérifier', shift: 'B', when: 'depuis 13 h', priority: false, action: 'VALIDATE' },
  { id: 'a5', cellId: 'C3', stationId: 'C3·P07', category: 'RYTHME', title: 'Retard de 18 pièces', detail: 'Rythme 112 / h depuis 15 h (objectif 125 / h)', shift: 'B', when: 'depuis 15 h', priority: false, action: 'VALIDATE' },
  { id: 'a6', cellId: 'C3', stationId: 'C3·P04', category: 'EQUIPEMENT', title: 'Caméra pièce hors ligne', detail: 'Le poste tourne sans contrôle qualité automatique', shift: 'B', when: 'depuis 16:07', priority: false, action: 'MAINTENANCE' },
];

const ep = (h1: number, m1: number, h2: number, m2: number): [number, number] => [(h1 - 13) * 60 + m1, (h2 - 13) * 60 + m2];
export const mockStationDetail: StationDetail = {
  stationId: 'C3·P06', product: 'Presse injection · raccord QC 702',
  efficiencyPct: 103, good: 476, expectedNow: 462, delta: 14, ratePerHour: 124,
  ko: 6, koRatePct: 1.2, koByDefect: { absent: 4, double: 2 },
  lanes: [
    { name: 'Sécurité', episodes: [ep(14, 12, 14, 14), ep(16, 38, 16, 40), ep(16, 41, 16, 42)] },
    { name: 'Poste', episodes: [ep(16, 37, 16, 40)] },
    { name: 'Qualité', episodes: [ep(15, 5, 15, 7), ep(15, 40, 15, 42), ep(16, 20, 16, 22)] },
    { name: 'Rythme', episodes: [ep(15, 10, 15, 25)], soft: true },
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
    { name: 'Qualité QC 702 · C3·P06', color: '#3D5A8A', values: [95, 95, 94, 95, 94, 93, 93, 92, 90, 89, 87, 85, 83, 81] },
    { name: 'EPI · UAP 2', color: '#0B1F3F', values: [93, 92, 93, 92, 91, 91, 90, 88, 87, 85, 83, 81, 80, 78] },
    { name: 'Téléphone · usine', color: '#9AAED0', values: [92, 92, 91, 92, 91, 90, 91, 90, 89, 89, 88, 89, 88, 88] },
  ],
  drifts: [
    { modelId: 'm2', title: 'Qualité QC 702 · poste C3·P06', detail: 'Santé 81 % (seuil 85 %) · dérive des données : images plus sombres depuis mardi', healthPct: 81, mode: 'MANUEL' },
    { modelId: 'm1', title: 'EPI · cellule 3 (12 postes)', detail: 'Santé 78 % · dérive de concept : nouveaux gants bleus. Auto planifié cette nuit à 2 h.', healthPct: 78, mode: 'AUTO', scheduledAt: '02:00' },
  ],
  models: [
    { id: 'm1', name: 'EPI casque-gants-lunettes', useCase: 'EPI', scope: 'UAP 2', version: 'v2.0', healthPct: 78 },
    { id: 'm2', name: 'Qualité QC 702', useCase: 'Qualité', scope: 'Poste C3·P06', version: 'v1.3', healthPct: 81, recallKoPct: 93 },
    { id: 'm3', name: 'Téléphone à la main', useCase: 'Comportement', scope: 'Toute l’usine', version: 'v1.1', healthPct: 88 },
    { id: 'm4', name: 'Zones poste rangé', useCase: 'Poste', scope: 'Toute l’usine', version: 'v1.0', healthPct: 94 },
    { id: 'm5', name: 'Qualité QC 702', useCase: 'Qualité', scope: 'UAP 1 et UAP 3', version: 'v1.3', healthPct: 95, recallKoPct: 95 },
  ],
  training: { modelName: 'Qualité QC 702', version: 'v1.4', dataset: 'jeu qc702 v3 · 839 images · 20 séquences · test par séquence entière', step: 3, recallKoPct: 96, previousRecallKoPct: 93, absentStoppedPct: 94, doubleStoppedPct: 100 },
  retrainMode: 'AUTO',
};

export const mockRoles: RoleDefinition[] = [
  { role: 'OPERATEUR', label: 'Opérateur', description: 'Rôle par défaut. Voit uniquement son poste.', permissions: ['VOIR_POSTE', 'SIGNALER'] },
  { role: 'TEAM_LEADER', label: 'Team leader', description: 'Suit les postes de sa cellule, consulte l’écran d’un poste et traite ses alertes.', permissions: ['VOIR_CELLULE', 'TRAITER_ALERTES'] },
  { role: 'AI_LEADER', label: 'AI Leader', description: 'Gère le cycle de vie des modèles.', permissions: ['VOIR_CELLULE', 'GERER_MODELES'] },
  { role: 'ADMIN', label: 'Admin', description: 'Gère les comptes, les rôles et les périmètres.', permissions: ['GERER_ACCES'] },
];

export const mockAppUsers: AppUser[] = [
  { id: 'u1', name: 'M. Rojas', login: 'm.rojas@hutchinson.com', badge: '004512', role: 'OPERATEUR', scope: 'Poste C3·P06', active: true, lastLogin: '26/11 13:02' },
  { id: 'u5', name: 'J. Pérez', login: 'j.perez@hutchinson.com', badge: '004518', role: 'OPERATEUR', scope: 'Poste C3·P05', active: true, lastLogin: '26/11 13:05' },
  { id: 'u6', name: 'L. Soto', login: 'l.soto@hutchinson.com', badge: '004533', role: 'OPERATEUR', scope: 'Poste C3·P04', active: false, lastLogin: '19/11 05:01' },
  { id: 'u2', name: 'C. Díaz', login: 'c.diaz@hutchinson.com', role: 'TEAM_LEADER', scope: 'Cellule 3 · UAP 2', active: true, lastLogin: '26/11 12:55' },
  { id: 'u3', name: 'A. Noui', login: 'a.noui@hutchinson.com', role: 'AI_LEADER', scope: 'Usine', active: true, lastLogin: '26/11 09:14' },
  { id: 'u4', name: 'Admin usine', login: 'admin@hutchinson.com', role: 'ADMIN', scope: 'Usine', active: true, lastLogin: '26/11 16:02' },
];

export const mockAudit: AuditEntry[] = [
  { at: '26/11 16:02', by: 'Admin usine', action: 'a désactivé le compte de L. Soto' },
  { at: '25/11 10:20', by: 'Admin usine', action: 'a rattaché C. Díaz à la cellule 3 (UAP 2)' },
  { at: '24/11 08:47', by: 'Admin usine', action: 'a créé le compte de J. Pérez (Opérateur, poste C3·P05)' },
];
