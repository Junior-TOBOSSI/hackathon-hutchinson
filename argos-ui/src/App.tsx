import type { ReactElement } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { LIVE_AI_LEADER, USE_MOCK } from './api/client';
import type { Role } from './api/types';
import { AuthProvider, homeFor, useAuth } from './auth';
import Admin from './pages/Admin';
import AiLeader from './pages/AiLeader';
import Cellule from './pages/Cellule';
import Login from './pages/Login';
import Operateur from './pages/Operateur';
import PosteDetail from './pages/PosteDetail';
import Superviseur from './pages/Superviseur';

/** Chaque route n'est ouverte qu'aux rôles listés ; sinon retour à l'accueil du rôle. */
function Guard({ roles, children }: { roles: Role[]; children: ReactElement }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/" replace />;
  if (!roles.includes(user.role)) return <Navigate to={homeFor[user.role]} replace />;
  return children;
}

/** Rappel permanent : en démo, les écrans affichent des données simulées. */
function DemoBadge() {
  if (!USE_MOCK) return null;
  return (
    <div className="pill pill-amber" style={{ position: 'fixed', left: 12, bottom: 12, zIndex: 50, boxShadow: '0 2px 8px rgba(11,31,63,.15)' }}>
      Démo · données simulées{LIVE_AI_LEADER ? ' (sauf AI Leader : données réelles)' : ''}
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <DemoBadge />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Login />} />
          <Route path="/operateur" element={<Guard roles={['OPERATEUR']}><Operateur /></Guard>} />
          {/* Écran mural : affiché en continu dans la cellule, sans connexion personnelle */}
          <Route path="/cellule" element={<Cellule />} />
          <Route path="/superviseur" element={<Guard roles={['SUPERVISEUR', 'AI_LEADER']}><Superviseur /></Guard>} />
          <Route path="/superviseur/poste/:id" element={<Guard roles={['SUPERVISEUR', 'AI_LEADER']}><PosteDetail /></Guard>} />
          <Route path="/ai-leader" element={<Guard roles={['AI_LEADER']}><AiLeader /></Guard>} />
          <Route path="/admin" element={<Guard roles={['ADMIN']}><Admin /></Guard>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
