import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// En dev, les appels /api sont redirigés vers le backend.
// ARGOS_API_TARGET choisit le backend (ex. http://127.0.0.1:8020 = Core + MLOps) ; défaut inchangé.
const target = process.env.ARGOS_API_TARGET ?? 'http://localhost:8000';
const edgeTarget = process.env.ARGOS_EDGE_TARGET ?? 'http://127.0.0.1:18041';
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': target, '/production': edgeTarget },
  },
});
