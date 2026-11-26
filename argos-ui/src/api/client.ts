// Point d'entrée unique vers le backend.
// Chaque fonction documente l'endpoint attendu. Tant que USE_MOCK vaut true,
// les données viennent de mock.ts : l'équipe backend remplace endpoint par endpoint.
//
// Temps réel conseillé : WebSocket /api/ws/stations/{id} et /api/ws/alerts
// qui poussent les mêmes objets que les GET ci-dessous (StationLive, Alert[]).
// Sans WebSocket, useApi() fait du polling (intervalle réglable).

import * as M from './mock';
import type {
  AiOverview, Alert, AppUser, AuditEntry, Role, RoleDefinition, StationDetail, StationLive, User, WorkshopOverview,
} from './types';

export const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'true') !== 'false';
/** AI Leader branché sur le backend réel (Databricks) même si les autres écrans restent en démo. */
export const LIVE_AI_LEADER = !USE_MOCK || import.meta.env.VITE_LIVE_AI_LEADER === 'true';
const BASE = import.meta.env.VITE_API_URL ?? '/api';

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} sur ${path}`);
  return res.status === 204 ? (undefined as T) : res.json();
}
const later = <T,>(v: T) => new Promise<T>((r) => setTimeout(() => r(structuredClone(v)), 120));

export const api = {
  /** POST /api/auth/login  {login, password} | {badge}  ->  User (rôle déduit des droits, OPERATEUR par défaut) */
  login(login: string, password: string): Promise<User> {
    if (USE_MOCK) return later(M.mockUsers[login.trim().toLowerCase()] ?? { id: 'x', name: login, role: 'OPERATEUR' as Role, stationId: 'A1·P06' });
    return http('/auth/login', { method: 'POST', body: JSON.stringify({ login, password }) });
  },

  /* ---------------- Opérateur ---------------- */
  /** GET /api/stations/{id}/live -> StationLive (le paramètre scenario n'existe qu'en démo) */
  stationLive(stationId: string, scenario: M.Scenario = 'ok'): Promise<StationLive> {
    if (USE_MOCK) return later(M.mockStationLive(scenario));
    return http(`/stations/${encodeURIComponent(stationId)}/live`);
  },
  /** POST /api/stations/{id}/report -> 204. Crée une alerte SIGNALEMENT chez le superviseur. */
  reportProblem(stationId: string): Promise<void> {
    if (USE_MOCK) return later(undefined);
    return http(`/stations/${encodeURIComponent(stationId)}/report`, { method: 'POST' });
  },

  /* ---------------- Superviseur ---------------- */
  /** GET /api/workshop/overview?date=YYYY-MM-DD -> WorkshopOverview */
  overview(): Promise<WorkshopOverview> {
    return USE_MOCK ? later(M.mockOverview) : http('/workshop/overview');
  },
  /** GET /api/alerts?status=open -> Alert[]  (déjà dédoublonnées : une alerte = un épisode par poste) */
  alerts(): Promise<Alert[]> {
    return USE_MOCK ? later(M.mockAlerts) : http('/alerts?status=open');
  },
  /** POST /api/alerts/{id}/decision {decision: 'VALIDER'|'REJETER'} -> 204. Un rejet alimente la santé du modèle. */
  decideAlert(id: string, decision: 'VALIDER' | 'REJETER'): Promise<void> {
    return USE_MOCK ? later(undefined) : http(`/alerts/${id}/decision`, { method: 'POST', body: JSON.stringify({ decision }) });
  },
  /** POST /api/alerts/{id}/maintenance -> 204 */
  callMaintenance(id: string): Promise<void> {
    return USE_MOCK ? later(undefined) : http(`/alerts/${id}/maintenance`, { method: 'POST' });
  },
  /** GET /api/stations/{id}/detail?shift=B -> StationDetail (aucune image) */
  stationDetail(stationId: string): Promise<StationDetail> {
    return USE_MOCK ? later(M.mockStationDetail) : http(`/stations/${encodeURIComponent(stationId)}/detail`);
  },

  /* ---------------- AI Leader ---------------- */
  /** GET /api/models/overview -> AiOverview (registre MLflow + santé calculée) */
  aiOverview(): Promise<AiOverview> {
    return USE_MOCK ? later(M.mockAi) : http('/models/overview');
  },
  /** POST /api/models/{id}/retrain -> 202 */
  retrain(modelId: string): Promise<void> {
    return USE_MOCK ? later(undefined) : http(`/models/${modelId}/retrain`, { method: 'POST' });
  },
  /** PUT /api/models/retrain-mode {mode} -> 204 */
  setRetrainMode(mode: 'MANUEL' | 'AUTO'): Promise<void> {
    return USE_MOCK ? later(undefined) : http('/models/retrain-mode', { method: 'PUT', body: JSON.stringify({ mode }) });
  },
  /** POST /api/models/{id}/promote {version} -> 204 */
  promote(modelId: string, version: string): Promise<void> {
    return USE_MOCK ? later(undefined) : http(`/models/${modelId}/promote`, { method: 'POST', body: JSON.stringify({ version }) });
  },

  /* ---------------- Admin ---------------- */
  /** GET /api/admin/users -> AppUser[] */
  users(): Promise<AppUser[]> {
    return USE_MOCK ? later(M.mockAppUsers) : http('/admin/users');
  },
  /** PATCH /api/admin/users/{id} {role?, scope?, active?} -> AppUser */
  updateUser(id: string, patch: Partial<Pick<AppUser, 'role' | 'scope' | 'active'>>): Promise<AppUser> {
    if (USE_MOCK) {
      const u = M.mockAppUsers.find((x) => x.id === id)!;
      Object.assign(u, patch);
      return later(u);
    }
    return http(`/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(patch) });
  },
  /** POST /api/admin/users {name, login, badge?, role, scope} -> AppUser */
  createUser(u: Omit<AppUser, 'id' | 'active' | 'lastLogin'>): Promise<AppUser> {
    if (USE_MOCK) {
      const created: AppUser = { ...u, id: 'u' + Date.now(), active: true };
      M.mockAppUsers.push(created);
      return later(created);
    }
    return http('/admin/users', { method: 'POST', body: JSON.stringify(u) });
  },
  /** GET /api/admin/roles -> RoleDefinition[] */
  roles(): Promise<RoleDefinition[]> {
    return USE_MOCK ? later(M.mockRoles) : http('/admin/roles');
  },
  /** GET /api/admin/audit -> AuditEntry[] */
  audit(): Promise<AuditEntry[]> {
    return USE_MOCK ? later(M.mockAudit) : http('/admin/audit');
  },
};
