import { useEffect, type ReactElement } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { USE_MOCK } from './api/client';
import type { Role, User } from './api/types';
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

/**
 * DÉMO uniquement : passer de la vue opérateur (poste C3·P06) à la vue team leader
 * (cellule C3) sans se déconnecter. Visible en mode démo ou avec VITE_DEMO_VIEWS=true ;
 * en production, chacun se connecte avec son propre compte.
 */
const DEMO_VIEWS = USE_MOCK || import.meta.env.VITE_DEMO_VIEWS === 'true';
const DEMO_USERS: { role: Role; label: string; user: User }[] = [
  { role: 'OPERATEUR', label: 'Opérateur', user: { id: 'demo', name: 'Opérateur démo', role: 'OPERATEUR', stationId: 'C3·P06', cellId: 'C3' } },
  { role: 'TEAM_LEADER', label: 'Team leader', user: { id: 'demo-tl', name: 'Team leader démo', role: 'TEAM_LEADER', cellId: 'C3' } },
];

/**
 * DÉMO : Ctrl+M passe de la vue opérateur à la vue team leader (superviseur), et retour.
 * Aucun signe à l'écran ; actif aussi en mode live, pour le pitch.
 */
function DemoShortcut() {
  const { user, setUser } = useAuth();
  const nav = useNavigate();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey && (e.key === 'm' || e.key === 'M'))) return;
      e.preventDefault();
      const next = user?.role === 'TEAM_LEADER' ? DEMO_USERS[0] : DEMO_USERS[1];
      setUser(next.user);
      nav(homeFor[next.role]);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [user, setUser, nav]);
  return null;
}

function DemoViewSwitch() {
  const { user, setUser } = useAuth();
  const nav = useNavigate();
  const { pathname } = useLocation();
  if (!DEMO_VIEWS || !user || !DEMO_USERS.some((d) => d.role === user.role) || pathname.startsWith('/tv')) return null;
  return (
    <div style={{ position: 'fixed', right: 16, bottom: 48, zIndex: 20, display: 'flex', gap: 4, padding: 4, borderRadius: 12, background: 'var(--navy)', boxShadow: '0 8px 24px rgba(0,0,0,.25)' }}>
      <span style={{ alignSelf: 'center', padding: '0 8px', fontSize: 12, color: 'var(--on-navy-muted)' }}>Vue</span>
      {DEMO_USERS.map((d) => (
        <button key={d.role} onClick={() => { setUser(d.user); nav(homeFor[d.role]); }}
          style={{ border: 'none', borderRadius: 9, padding: '7px 14px', fontWeight: 700, fontSize: 14, color: '#fff', background: user.role === d.role ? 'var(--primary)' : 'transparent', outline: user.role === d.role ? '1px solid var(--on-navy-muted)' : 'none' }}>
          {d.label}
        </button>
      ))}
    </div>
  );
}

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
        <DemoViewSwitch />
        <DemoShortcut />
      </BrowserRouter>
    </AuthProvider>
  );
}
