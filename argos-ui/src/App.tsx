import type { ReactElement } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';
import type { Role } from './api/types';
import { AuthProvider, homeFor, useAuth } from './auth';
import Admin from './pages/Admin';
import AiLeader from './pages/AiLeader';
import CelluleTV from './pages/CelluleTV';
import Login from './pages/Login';
import Operateur from './pages/Operateur';
import PosteDetail from './pages/PosteDetail';
import PosteVoyants from './pages/PosteVoyants';
import TeamLeader from './pages/TeamLeader';

/** Chaque route n'est ouverte qu'aux rôles listés ; sinon retour à l'accueil du rôle. */
function Guard({ roles, children }: { roles: Role[]; children: ReactElement }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/" replace />;
  if (!roles.includes(user.role)) return <Navigate to={homeFor[user.role]} replace />;
  return children;
}

/** Le team leader consulte l'écran d'un poste de sa cellule : le même écran que l'opérateur. */
function StationScreenForTeamLeader() {
  const { id = 'C3·P06' } = useParams();
  return <Operateur consultStationId={id} />;
}

const CELL_ROLES: Role[] = ['TEAM_LEADER', 'AI_LEADER'];

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Login />} />
          <Route path="/operateur" element={<Guard roles={['OPERATEUR']}><Operateur /></Guard>} />
          {/* Écrans fixes, sans connexion personnelle */}
          <Route path="/tv/:cellId" element={<CelluleTV />} />
          <Route path="/poste/:stationId/voyants" element={<PosteVoyants />} />
          {/* Team leader : les postes de sa cellule */}
          <Route path="/team-leader" element={<Guard roles={CELL_ROLES}><TeamLeader /></Guard>} />
          <Route path="/team-leader/poste/:id" element={<Guard roles={CELL_ROLES}><StationScreenForTeamLeader /></Guard>} />
          <Route path="/team-leader/poste/:id/historique" element={<Guard roles={CELL_ROLES}><PosteDetail /></Guard>} />
          <Route path="/ai-leader" element={<Guard roles={['AI_LEADER']}><AiLeader /></Guard>} />
          <Route path="/admin" element={<Guard roles={['ADMIN']}><Admin /></Guard>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
