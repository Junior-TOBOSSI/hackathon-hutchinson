import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { homeFor, useAuth } from '../auth';
import { Icon, ICONS } from '../components/ui';

export default function Login() {
  const [login, setLogin] = useState('m.rojas@hutchinson.com');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const { setUser } = useAuth();
  const nav = useNavigate();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const u = await api.login(login, password);
      setUser(u);
      nav(homeFor[u.role]); // le rôle vient des droits du compte ; opérateur par défaut
    } catch {
      setError('Identifiant ou mot de passe incorrect.');
    }
  };

  const input = { height: 48, border: '2px solid #c9d4e5', borderRadius: 12, padding: '0 16px', fontFamily: 'var(--font)', fontSize: 17, color: 'var(--ink)' };

  return (
    <div style={{ minHeight: '100vh', background: 'radial-gradient(ellipse 60% 55% at 50% 28%, #0b2d5e 0%, #02162f 70%)', color: '#fff', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px 16px' }}>
      {/* Logo en relief : le buste sort d'une sphère */}
      <div style={{ position: 'relative', width: 420, maxWidth: '100%', height: 330, perspective: 900 }}>
        <div style={{ position: 'absolute', left: '50%', top: 30, width: 300, height: 300, marginLeft: -150, borderRadius: '50%', background: 'radial-gradient(circle, rgba(70,170,255,.4) 40%, rgba(70,170,255,0) 70%)' }} />
        <div style={{ position: 'absolute', left: '50%', top: 60, width: 250, height: 250, marginLeft: -125, borderRadius: '50%', overflow: 'hidden', background: 'radial-gradient(circle at 34% 28%, #4a92f0 0%, #1550a8 30%, #062a62 62%, #010e24 100%)', boxShadow: '0 34px 50px rgba(0,0,0,.65), inset -20px -26px 44px rgba(0,0,0,.6), inset 12px 14px 30px rgba(150,210,255,.3)' }}>
          <svg width="250" height="250" viewBox="0 0 250 250" aria-hidden="true" style={{ position: 'absolute', inset: 0 }}>
            <g fill="none" stroke="#9fd0ff" strokeOpacity="0.22" strokeWidth="1.5">
              <ellipse cx="125" cy="125" rx="124" ry="40" /><ellipse cx="125" cy="125" rx="124" ry="85" />
              <ellipse cx="125" cy="125" rx="40" ry="124" /><ellipse cx="125" cy="125" rx="85" ry="124" />
            </g>
          </svg>
        </div>
        <img src="/img/argos-buste.png" alt="Buste d'Argos aux yeux connectés" style={{ position: 'absolute', left: '50%', top: 0, width: 360, marginLeft: -180, transform: 'translateZ(70px) rotateY(-10deg) rotateX(4deg)', filter: 'drop-shadow(0 20px 18px rgba(0,0,0,.6)) drop-shadow(0 0 16px rgba(90,200,255,.5))' }} />
      </div>
      <div style={{ width: 260, height: 26, borderRadius: '50%', background: 'radial-gradient(ellipse at center, rgba(0,0,0,.55) 0%, rgba(0,0,0,0) 70%)' }} />
      <img src="/img/argos-wordmark.png" alt="ARGOS" style={{ marginTop: 6, width: 440, maxWidth: '90%', filter: 'drop-shadow(0 10px 16px rgba(0,0,0,.6)) drop-shadow(0 0 14px rgba(90,200,255,.35))' }} />
      <span className="cond" style={{ marginTop: 14, fontWeight: 600, fontSize: 20, letterSpacing: '0.2em', textAlign: 'center' }}>VISION INTELLIGENTE AU SERVICE DE LA PERFORMANCE INDUSTRIELLE</span>

      <form onSubmit={submit} style={{ marginTop: 24, width: 530, maxWidth: '100%', background: '#fff', color: 'var(--ink)', borderRadius: 24, padding: '24px 30px', display: 'flex', flexDirection: 'column', gap: 12, boxShadow: '0 24px 60px rgba(0,0,0,.45)' }}>
        <label htmlFor="ident" style={{ fontSize: 15, fontWeight: 600 }}>Identifiant ou adresse e-mail</label>
        <input id="ident" value={login} onChange={(e) => setLogin(e.target.value)} style={input} autoComplete="username" />
        <label htmlFor="mdp" style={{ fontSize: 15, fontWeight: 600 }}>Mot de passe</label>
        <input id="mdp" type="password" value={password} onChange={(e) => setPassword(e.target.value)} style={input} autoComplete="current-password" />
        {error && <span style={{ color: 'var(--red-text)', fontWeight: 600 }}>{error}</span>}
        <button type="submit" className="cond" style={{ height: 52, borderRadius: 14, border: 'none', background: 'var(--blue)', color: '#fff', fontWeight: 700, fontSize: 22, letterSpacing: '0.04em' }}>Se connecter</button>
        <div className="row" style={{ justifyContent: 'center', gap: 10, fontSize: 15 }}>
          <Icon d={ICONS.badge} size={26} color="var(--blue)" />
          <span>Au poste : passez votre badge sur le lecteur</span>
        </div>
        <span className="muted" style={{ fontSize: 12, textAlign: 'center' }}>
          Démo : m.rojas@ (opérateur) · c.diaz@ (superviseur) · a.noui@ (AI Leader) · admin@ (admin), domaine hutchinson.com
        </span>
      </form>
    </div>
  );
}
