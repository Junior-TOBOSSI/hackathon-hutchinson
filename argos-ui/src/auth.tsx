import { createContext, useContext, useState, type ReactNode } from 'react';
import type { Role, User } from './api/types';

interface AuthCtx {
  user: User | null;
  setUser: (u: User | null) => void;
}
const Ctx = createContext<AuthCtx>({ user: null, setUser: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(() => {
    try {
      const raw = sessionStorage.getItem('hovis.user');
      return raw ? (JSON.parse(raw) as User) : null;
    } catch {
      return null;
    }
  });
  const setUser = (u: User | null) => {
    setUserState(u);
    try {
      if (u) sessionStorage.setItem('hovis.user', JSON.stringify(u));
      else sessionStorage.removeItem('hovis.user');
    } catch {
      /* stockage indisponible : la session reste en mémoire */
    }
  };
  return <Ctx.Provider value={{ user, setUser }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);

/** Page d'accueil de chaque rôle après connexion. */
export const homeFor: Record<Role, string> = {
  OPERATEUR: '/operateur',
  SUPERVISEUR: '/superviseur',
  AI_LEADER: '/ai-leader',
  ADMIN: '/admin',
};
