export type ApiMode = "mock" | "live";

const env = import.meta.env;

export const config = {
  mode: (env.VITE_API_MODE === "live" ? "live" : "mock") as ApiMode,
  /** Local Edge backend of THIS station (Operator space). */
  edgeBaseUrl: env.VITE_EDGE_API_URL || "/edge-api",
  /** Central ARGOS Core (Supervisor and AI Leader spaces). */
  coreBaseUrl: env.VITE_CORE_API_URL || "/core-api",
  stationId: env.VITE_STATION_ID || "WS-01",
};
