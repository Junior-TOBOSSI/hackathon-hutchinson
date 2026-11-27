import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { homeFor, useAuth } from '../auth';
import { HovisLogo } from '../components/brand';
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

  const input = { height: 48, border: '2px solid var(--line-strong)', borderRadius: 12, padding: '0 16px', fontFamily: 'var(--font)', fontSize: 17, color: 'var(--ink)' };

  return (
    <div style={{ minHeight: '100vh', background: 'var(--navy)', color: '#fff', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px 16px' }}>
      {/* Logo complet de la charte HOVIS (symbole | HOVIS + signature) sur fond marine. */}
      <div className="login-logo">
        <HovisLogo size={96} tone="light" tagline />
      </div>

      <form onSubmit={submit} style={{ marginTop: 48, width: 530, maxWidth: '100%', background: '#fff', color: 'var(--ink)', borderRadius: 24, padding: '24px 30px', display: 'flex', flexDirection: 'column', gap: 12, boxShadow: '0 24px 60px rgba(0, 0, 0, .35)' }}>
        <label htmlFor="ident" style={{ fontSize: 15, fontWeight: 600 }}>Identifiant ou adresse e-mail</label>
        <input id="ident" value={login} onChange={(e) => setLogin(e.target.value)} style={input} autoComplete="username" />
        <label htmlFor="mdp" style={{ fontSize: 15, fontWeight: 600 }}>Mot de passe</label>
        <input id="mdp" type="password" value={password} onChange={(e) => setPassword(e.target.value)} style={input} autoComplete="current-password" />
        {error && <span style={{ color: 'var(--red-text)', fontWeight: 600 }}>{error}</span>}
        <button type="submit" className="cond" style={{ height: 52, borderRadius: 14, border: 'none', background: 'var(--primary)', color: '#fff', fontWeight: 500, fontSize: 19, letterSpacing: '0.12em', textTransform: 'uppercase' }}>Se connecter</button>
        <div className="row" style={{ justifyContent: 'center', gap: 10, fontSize: 15 }}>
          <Icon d={ICONS.badge} size={26} color="var(--primary)" />
          <span>Au poste : passez votre badge sur le lecteur</span>
        </div>
      </form>
    </div>
  );
}
