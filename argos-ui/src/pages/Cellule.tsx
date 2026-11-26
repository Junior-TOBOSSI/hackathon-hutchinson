import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { Scenario } from '../api/mock';
import { HovisLogo } from '../components/brand';
import { Clock, Icon, ICONS, Loading } from '../components/ui';
import { useApi } from '../hooks/useApi';

/** Écran mural de la cellule : 4 voyants lisibles de loin. Route : /cellule/:stationId */
export default function Cellule() {
  const [params] = useSearchParams();
  const scenario = (params.get('scenario') as Scenario) || 'multi';
  const { data: live } = useApi(() => api.stationLive('A1·P06', scenario), [scenario], 2000);
  if (!live) return <Loading />;

  const has = (c: string) => live.issues.find((i) => i.category === c);
  const tiles = [
    { title: 'Environnement sûr', icon: ICONS.shield, issue: has('COMPORTEMENT') },
    { title: 'Pas d’objet étranger', icon: ICONS.grid, issue: has('POSTE') },
    { title: 'EPI portés', icon: ICONS.shield, issue: has('SECURITE_EPI') },
    { title: 'Poste rangé', icon: ICONS.grid, issue: undefined },
  ];

  return (
    <div style={{ minHeight: '100vh', background: 'var(--navy)', color: '#fff', padding: '36px 48px', display: 'flex', flexDirection: 'column', gap: 28 }}>
      <div className="row" style={{ gap: 16 }}>
        <HovisLogo size={44} tone="light" />
        <span className="cond" style={{ fontWeight: 700, fontSize: 40 }}>POSTE {live.stationId}</span>
        <span style={{ flex: 1 }} />
        <Clock iso={live.now} />
      </div>
      <div className="grid-2" style={{ flex: 1, gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 24 }}>
        {tiles.map((t) => (
          <div key={t.title} style={{ background: t.issue ? 'var(--red-deep)' : 'var(--navy-2)', border: t.issue ? '3px solid var(--red-on-navy)' : '3px solid transparent', borderRadius: 30, padding: 25, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 22 }}>
            <div style={{ flex: 1, width: 120, minHeight: 260, borderRadius: 60, background: t.issue ? 'var(--red)' : 'var(--green)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Icon d={t.icon} size={56} color="#fff" stroke={2.2} />
            </div>
            <span className="cond" style={{ fontWeight: 700, fontSize: 30, textAlign: 'center', lineHeight: 1.05 }}>{t.issue ? t.issue.label : t.title}</span>
            {t.issue && <span style={{ fontSize: 18, color: 'var(--red-light)' }}>{t.issue.instruction}</span>}
          </div>
        ))}
      </div>
      <div className="between" style={{ color: 'var(--on-navy-muted)', fontSize: 15 }}>
        <span>Caméra frontale · visage flouté · analyse en mémoire, rien n’est enregistré</span>
        <span>Dernière pièce : {live.part.verdict} · {live.counters.good} / {live.objective.shiftTarget}</span>
      </div>
    </div>
  );
}
