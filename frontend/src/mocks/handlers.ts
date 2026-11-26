// Mock mode: answers the Edge and Core API calls with the SYNTHETIC fixtures exported by
// `python -m visionhub.integration.export` (validated against the Python contracts).
import { ApiError } from "../api/errors";
import type { ApiTarget } from "../api/http";
import alerts from "./fixtures/core/alerts.json";
import deployments from "./fixtures/core/deployments.json";
import models from "./fixtures/core/models.json";
import monitoring from "./fixtures/core/monitoring.json";
import operatorReports from "./fixtures/core/operator-reports.json";
import retrainingPolicies from "./fixtures/core/retraining-policies.json";
import stations from "./fixtures/core/stations.json";
import trainingJobs from "./fixtures/core/training-jobs.json";
import events from "./fixtures/edge/events.json";
import health from "./fixtures/edge/health.json";
import kpi from "./fixtures/edge/production-kpi.json";
import corrections from "./fixtures/edge/production-part-corrections.json";
import parts from "./fixtures/edge/production-parts.json";
import shiftCurrent from "./fixtures/edge/production-shift-current.json";
import stats from "./fixtures/edge/stats.json";
import useCases from "./fixtures/edge/use-cases.json";

type Handler = (match: RegExpMatchArray, init: RequestInit) => unknown;
interface Route {
  target: ApiTarget;
  method: string;
  pattern: RegExp;
  handler: Handler;
}

const route = (target: ApiTarget, method: string, pattern: RegExp, handler: Handler): Route => ({
  target,
  method,
  pattern,
  handler,
});
const notFound = (what: string) => {
  throw new ApiError(404, `${what} not found (mock)`);
};
const byId = <T extends Record<string, unknown>>(items: T[], key: keyof T, id: string) =>
  items.find((item) => item[key] === id) ?? notFound(`${String(key)} ${id}`);

// Mutable copy so that mock corrections are visible until the page reloads.
const mockParts = structuredClone(parts) as Array<Record<string, unknown>>;

const routes: Route[] = [
  // ---- Edge (implemented endpoints)
  route("edge", "GET", /^\/health$/, () => health),
  route("edge", "GET", /^\/use-cases$/, () => useCases),
  route("edge", "GET", /^\/events(\?.*)?$/, () => events),
  route("edge", "GET", /^\/stats$/, () => stats),
  route("edge", "GET", /^\/production\/parts(\?.*)?$/, () => mockParts),
  route("edge", "GET", /^\/production\/parts\/([^/?]+)$/, (m) => byId(mockParts, "part_id", m[1])),
  route("edge", "GET", /^\/production\/parts\/([^/?]+)\/corrections$/, (m) =>
    corrections.filter((c) => c.part_id === m[1]),
  ),
  route("edge", "POST", /^\/production\/parts\/([^/?]+)\/corrections$/, (m, init) => {
    const part = byId(mockParts, "part_id", m[1]);
    const body = JSON.parse(String(init.body));
    if (part.effective_verdict !== body.expected_current_verdict) {
      throw new ApiError(409, "part changed meanwhile (mock)");
    }
    part.effective_verdict = body.new_verdict;
    part.correction_count = Number(part.correction_count) + 1;
    return part;
  }),
  route("edge", "GET", /^\/production\/stations\/[^/]+\/shifts\/current$/, () => shiftCurrent),
  route("edge", "GET", /^\/production\/stations\/[^/]+\/kpi(\?.*)?$/, () => kpi),
  // ---- Core (to be developed)
  route("core", "GET", /^\/api\/v1\/stations$/, () => stations),
  route("core", "GET", /^\/api\/v1\/stations\/([^/?]+)$/, (m) => byId(stations, "station_id", m[1])),
  route("core", "GET", /^\/api\/v1\/alerts(\?.*)?$/, () => alerts),
  route("core", "GET", /^\/api\/v1\/operator-reports$/, () => operatorReports),
  route("core", "GET", /^\/api\/v1\/models$/, () => models),
  route("core", "GET", /^\/api\/v1\/deployments$/, () => deployments),
  route("core", "GET", /^\/api\/v1\/monitoring(\?.*)?$/, () => monitoring),
  route("core", "GET", /^\/api\/v1\/training-jobs$/, () => trainingJobs),
  route("core", "GET", /^\/api\/v1\/retraining-policies$/, () => retrainingPolicies),
];

export async function mockFetch<T>(target: ApiTarget, path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  await new Promise((resolve) => setTimeout(resolve, 120));
  for (const r of routes) {
    const match = r.target === target && r.method === method ? path.match(r.pattern) : null;
    if (match) return structuredClone(r.handler(match, init)) as T;
  }
  throw new ApiError(501, `No mock for ${method} ${target}${path}`);
}
