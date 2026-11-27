/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCK?: string;
  /** "true" : sélecteur de vue Opérateur | Team leader en démo locale */
  readonly VITE_DEMO_VIEWS?: string;
  readonly VITE_API_URL?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
