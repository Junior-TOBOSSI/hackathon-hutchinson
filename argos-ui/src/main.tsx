import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
// Police Jost servie depuis node_modules : aucune requête vers un service externe.
import '@fontsource-variable/jost';
import './theme.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
