import { useState, type FormEvent } from 'react';
import { api } from '../api/client';
import type { AppUser, Permission, Role } from '../api/types';
import { Icon, ICONS, Loading, TopBar } from '../components/ui';
import { useApi } from '../hooks/useApi';

/** Admin : gère les comptes, les rôles et les périmètres. Tout nouveau compte est opérateur par défaut. */
const ROLE_LABEL: Record<Role, string> = { OPERATEUR: 'Opérateur', SUPERVISEUR: 'Superviseur', AI_LEADER: 'AI Leader', ADMIN: 'Admin' };
const PERM_LABEL: Record<Permission, string> = {
  VOIR_POSTE: 'Voir l’écran du poste', SIGNALER: 'Signaler un problème', VOIR_COCKPIT: 'Voir l’atelier (lignes, cellules)',
  TRAITER_ALERTES: 'Traiter les alertes', GERER_MODELES: 'Entraîner et déployer les modèles', GERER_ACCES: 'Gérer les comptes et les rôles',
};
type Tab = 'users' | 'roles' | 'audit';

export default function Admin() {
  const { data: users, setData: setUsers } = useApi(() => api.users(), []);
  const { data: roles } = useApi(() => api.roles(), []);
  const { data: audit } = useApi(() => api.audit(), []);
  const [tab, setTab] = useState<Tab>('users');
  const [q, setQ] = useState('');
  const [showNew, setShowNew] = useState(false);

  if (!users || !roles || !audit) return <Loading />;
  const patch = async (u: AppUser, p: Partial<AppUser>) => {
    const updated = await api.updateUser(u.id, p);
    setUsers(users.map((x) => (x.id === u.id ? { ...updated } : x)));
  };
  const shown = users.filter((u) => (u.name + u.login + u.scope).toLowerCase().includes(q.toLowerCase()));
  const tabs: { key: Tab; label: string; icon: string }[] = [
    { key: 'users', label: 'Utilisateurs', icon: ICONS.users }, { key: 'roles', label: 'Rôles et droits', icon: ICONS.key }, { key: 'audit', label: 'Journal', icon: ICONS.log },
  ];

  return (
    <div className="screen">
      <TopBar title="Administration des accès" sub="Usine du Chili" />
      <nav className="tabs" role="tablist">
        {tabs.map((t) => <button key={t.key} role="tab" aria-selected={tab === t.key} className="tab" onClick={() => setTab(t.key)}><Icon d={t.icon} size={22} />{t.label}</button>)}
      </nav>
      <main className="col page-sup" style={{ padding: '20px 24px', gap: 16 }}>
        {tab === 'users' && (
          <>
            <div className="grid-3" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }}>
              {(['OPERATEUR', 'SUPERVISEUR', 'AI_LEADER', 'ADMIN'] as Role[]).map((r) => (
                <div key={r} className="card"><div className="muted" style={{ fontSize: 14, fontWeight: 600 }}>{ROLE_LABEL[r]}s</div><div className="num" style={{ fontSize: 36 }}>{users.filter((u) => u.role === r && u.active).length}</div></div>
              ))}
            </div>
            <div className="row stack-mobile">
              <label htmlFor="q" className="hide-mobile" style={{ fontWeight: 600 }}>Rechercher</label>
              <input id="q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nom, identifiant ou poste" style={{ height: 44, borderRadius: 12, border: '2px solid var(--line)', padding: '0 14px', fontSize: 15, minWidth: 280 }} />
              <span style={{ flex: 1 }} />
              <button className="btn btn-primary" onClick={() => setShowNew(true)}>+ Ajouter un utilisateur</button>
            </div>
            {showNew && <NewUser onCancel={() => setShowNew(false)} onCreated={(u) => { setUsers([...users, u]); setShowNew(false); }} />}
            <div className="card" style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 900, fontSize: 15 }}>
                <thead><tr className="muted" style={{ fontSize: 13, textAlign: 'left', letterSpacing: '0.06em' }}>
                  <th style={{ padding: '8px 0' }}>NOM</th><th>IDENTIFIANT</th><th>BADGE</th><th>RÔLE</th><th>PÉRIMÈTRE</th><th>DERNIÈRE CONNEXION</th><th>ACCÈS</th>
                </tr></thead>
                <tbody>
                  {shown.map((u) => (
                    <tr key={u.id} style={{ borderTop: '1px solid var(--line-soft)', opacity: u.active ? 1 : 0.55 }}>
                      <td style={{ padding: '10px 0', fontWeight: 700 }}>{u.name}</td>
                      <td className="muted">{u.login}</td>
                      <td className="muted">{u.badge ?? '—'}</td>
                      <td>
                        <select aria-label={`Rôle de ${u.name}`} value={u.role} onChange={(e) => patch(u, { role: e.target.value as Role })} style={{ height: 38, borderRadius: 10, border: '2px solid var(--line)', padding: '0 8px', fontSize: 15, fontFamily: 'inherit' }}>
                          {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select>
                      </td>
                      <td>
                        <input aria-label={`Périmètre de ${u.name}`} defaultValue={u.scope} onBlur={(e) => e.target.value !== u.scope && patch(u, { scope: e.target.value })} style={{ height: 38, borderRadius: 10, border: '2px solid var(--line)', padding: '0 10px', fontSize: 15, width: 170 }} />
                      </td>
                      <td className="muted">{u.lastLogin ?? '—'}</td>
                      <td>
                        <button onClick={() => patch(u, { active: !u.active })} className={`pill ${u.active ? 'pill-green' : 'pill-red'}`} style={{ border: 'none', padding: '8px 12px' }}>{u.active ? 'Actif' : 'Désactivé'}</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <span className="muted" style={{ fontSize: 13 }}>Un compte sans rôle attribué ouvre l’écran opérateur. Chaque modification est inscrite au journal.</span>
          </>
        )}

        {tab === 'roles' && (
          <div className="card" style={{ overflowX: 'auto' }}>
            <h2 className="h2" style={{ marginBottom: 12 }}>Ce que chaque rôle peut faire</h2>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 720, fontSize: 15 }}>
              <thead><tr><th style={{ textAlign: 'left', padding: '8px 0' }} className="muted">DROIT</th>{roles.map((r) => <th key={r.role} style={{ padding: '8px 6px' }}>{r.label}</th>)}</tr></thead>
              <tbody>
                {(Object.keys(PERM_LABEL) as Permission[]).map((p) => (
                  <tr key={p} style={{ borderTop: '1px solid var(--line-soft)' }}>
                    <td style={{ padding: '12px 0' }}>{PERM_LABEL[p]}</td>
                    {roles.map((r) => (
                      <td key={r.role} style={{ textAlign: 'center' }}>
                        {r.permissions.includes(p) ? <span style={{ display: 'inline-flex', width: 28, height: 28, borderRadius: 14, background: 'var(--green)', alignItems: 'center', justifyContent: 'center' }}><Icon d={ICONS.check} size={16} color="#fff" stroke={3} /></span> : <span className="muted">—</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="grid-2" style={{ marginTop: 16, gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }}>
              {roles.map((r) => <div key={r.role} className="col" style={{ gap: 4, padding: 12, borderRadius: 14, background: 'var(--primary-soft)' }}><b>{r.label}</b><span className="muted" style={{ fontSize: 14 }}>{r.description}</span></div>)}
            </div>
          </div>
        )}

        {tab === 'audit' && (
          <div className="card col" style={{ gap: 0 }}>
            <h2 className="h2" style={{ marginBottom: 10 }}>Journal des modifications d’accès</h2>
            {audit.map((a, i) => (
              <div key={i} className="row" style={{ padding: '12px 0', borderTop: i ? '1px solid var(--line-soft)' : 'none' }}>
                <span className="cond" style={{ width: 120, fontWeight: 700, fontSize: 18 }}>{a.at}</span>
                <span><b>{a.by}</b> {a.action}</span>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function NewUser({ onCancel, onCreated }: { onCancel: () => void; onCreated: (u: AppUser) => void }) {
  const [f, setF] = useState({ name: '', login: '', badge: '', role: 'OPERATEUR' as Role, scope: '' });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    onCreated(await api.createUser({ ...f, badge: f.badge || undefined }));
  };
  const field = { height: 44, borderRadius: 12, border: '2px solid var(--line)', padding: '0 12px', fontSize: 15, fontFamily: 'inherit' };
  return (
    <form onSubmit={submit} className="card" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12, alignItems: 'end' }}>
      <label className="col" style={{ gap: 6 }}>Nom<input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} style={field} /></label>
      <label className="col" style={{ gap: 6 }}>Identifiant ou e-mail<input required value={f.login} onChange={(e) => setF({ ...f, login: e.target.value })} style={field} /></label>
      <label className="col" style={{ gap: 6 }}>Badge<input value={f.badge} onChange={(e) => setF({ ...f, badge: e.target.value })} style={field} /></label>
      <label className="col" style={{ gap: 6 }}>Rôle
        <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })} style={field}>
          {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      <label className="col" style={{ gap: 6 }}>Périmètre<input required placeholder="Poste A1·P06, Ligne A…" value={f.scope} onChange={(e) => setF({ ...f, scope: e.target.value })} style={field} /></label>
      <div className="row"><button type="submit" className="btn btn-primary grow">Créer</button><button type="button" className="btn btn-ghost" onClick={onCancel}>Annuler</button></div>
    </form>
  );
}
