/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_MODE?: "mock" | "live";
  readonly VITE_EDGE_API_URL?: string;
  readonly VITE_CORE_API_URL?: string;
  readonly VITE_STATION_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
