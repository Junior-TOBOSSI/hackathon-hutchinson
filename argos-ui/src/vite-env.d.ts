/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCK?: string;
  readonly VITE_API_URL?: string;
  readonly VITE_LIVE_AI_LEADER?: string;
  readonly VITE_LIVE_INDUSTRIAL?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
