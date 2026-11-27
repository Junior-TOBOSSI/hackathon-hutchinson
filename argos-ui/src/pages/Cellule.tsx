import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { Scenario } from '../api/mock';
import { HovisLogo } from '../components/brand';
import { Clock, Icon, ICONS, Loading } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { industrial, LIVE_INDUSTRIAL } from '../api/industrial';
import { cellView } from '../api/industrial-view';

/** Écran mural de la cellule : 4 voyants lisibles de loin. Route : /cellule/:stationId */
export default function Cellule() {
  const [params, setParams] = useSearchParams();
  const scenario = (params.get('scenario') as Scenario) || 'multi';
  const { data: stations, error: stationsError } = useApi(() => LIVE_INDUSTRIAL ? industrial.stations() : Promise.resolve([]), [], LIVE_INDUSTRIAL ? 2000 : 0);
  const selected = stations?.find((station) => station.station_id === params.get('station'))?.station_id ?? stations?.[0]?.station_id;
  const { data: real, error } = useApi(() => LIVE_INDUSTRIAL && selected ? cellView(selected) : Promise.resolve(null), [selected], LIVE_INDUSTRIAL ? 2000 : 0);
  const { data: mock } = useApi(() => LIVE_INDUSTRIAL ? Promise.resolve(null) : api.stationLive('A1·P06', scenario), [scenario], LIVE_INDUSTRIAL ? 0 : 2000);
  const current = real?.station.station_id === selected ? real : null;
  if (!LIVE_INDUSTRIAL && !mock || LIVE_INDUSTRIAL && !current && !error && !stationsError) return <Loading />;

  const has = (c: string) => mock?.issues.find((i) => i.category === c);
  const observed = current?.alerts;
  const behavior = observed?.find((a) => a.use_case === 'safety' && (a.alert_type.startsWith('behavior.') || a.alert_type === 'safety.decision'));
  const ppe = observed?.find((a) => a.use_case === 'safety' && a.alert_type.startsWith('ppe.'));
  const object = observed?.find((a) => a.use_case === 'workstation' && /object|foreign/.test(a.alert_type));
  const workstation = observed?.find((a) => a.use_case === 'workstation');
  const tiles = [
    { title: 'Environnement sûr', icon: ICONS.shield, issue: LIVE_INDUSTRIAL ? behavior && { label: behavior.title, instruction: behavior.simulated ? 'Observation synthétique' : 'Observation signalée' } : has('COMPORTEMENT'), known: !LIVE_INDUSTRIAL },
    { title: 'Pas d’objet étranger', icon: ICONS.grid, issue: LIVE_INDUSTRIAL ? object && { label: object.title, instruction: object.simulated ? 'Observation synthétique' : 'Observation signalée' } : has('POSTE'), known: !LIVE_INDUSTRIAL },
    { title: 'EPI portés', icon: ICONS.shield, issue: LIVE_INDUSTRIAL ? ppe && { label: ppe.title, instruction: ppe.simulated ? 'Observation synthétique' : 'Observation signalée' } : has('SECURITE_EPI'), known: !LIVE_INDUSTRIAL },
    { title: 'Poste rangé', icon: ICONS.grid, issue: LIVE_INDUSTRIAL ? workstation && { label: workstation.title, instruction: workstation.simulated ? 'Observation synthétique' : 'Observation signalée' } : undefined, known: !LIVE_INDUSTRIAL },
  ];

  return (
    <div style={{ minHeight: '100vh', background: 'var(--navy)', color: '#fff', padding: '36px 48px', display: 'flex', flexDirection: 'column', gap: 28 }}>
      <div className="row" style={{ gap: 16 }}>
        <HovisLogo size={44} tone="light" />
        <span className="cond" style={{ fontWeight: 700, fontSize: 40 }}>POSTE {LIVE_INDUSTRIAL ? selected ?? 'indisponible' : mock?.stationId}</span>
        <span style={{ flex: 1 }} />
        <Clock iso={LIVE_INDUSTRIAL ? new Date().toISOString() : mock!.now} />
      </div>
      {LIVE_INDUSTRIAL && <div className="row" style={{ gap: 12 }}><label>Poste <select className="btn" value={selected ?? ''} onChange={(event) => setParams({ station: event.target.value })}>{stations?.map((station) => <option key={station.station_id} value={station.station_id}>{station.station_id}</option>)}</select></label>{(error || stationsError) && <span style={{ color: 'var(--red-light)' }}>Connexion interrompue · {error ?? stationsError}</span>}</div>}
      <div className="grid-2" style={{ flex: 1, gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 24 }}>
        {tiles.map((t) => (
          <div key={t.title} style={{ background: t.issue ? 'var(--red-deep)' : 'var(--navy-2)', border: t.issue ? '3px solid var(--red-on-navy)' : '3px solid transparent', borderRadius: 30, padding: 25, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 22 }}>
            <div style={{ flex: 1, width: 120, minHeight: 260, borderRadius: 60, background: t.issue ? 'var(--red)' : t.known ? 'var(--green)' : 'var(--amber)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Icon d={t.icon} size={56} color="#fff" stroke={2.2} />
            </div>
            <span className="cond" style={{ fontWeight: 700, fontSize: 30, textAlign: 'center', lineHeight: 1.05 }}>{t.issue?.label ?? t.title}</span>
            {t.issue && <span style={{ fontSize: 18, color: 'var(--red-light)' }}>{t.issue.instruction}</span>}
            {!t.issue && !t.known && <span style={{ fontSize: 18, color: 'var(--on-navy-muted)' }}>État inconnu</span>}
          </div>
        ))}
      </div>
      <div className="between" style={{ color: 'var(--on-navy-muted)', fontSize: 15 }}>
        <span>{LIVE_INDUSTRIAL ? `Image indisponible · caméra ${current?.station.equipment.find((item) => item.equipment_type === 'camera')?.status ?? 'état inconnu'}` : 'Caméra frontale · visage flouté · analyse en mémoire, rien n’est enregistré'}</span>
        <span>Dernière pièce : {LIVE_INDUSTRIAL ? current?.part?.effective_verdict ?? 'indisponible' : mock?.part.verdict} · {LIVE_INDUSTRIAL ? 'objectif non affiché' : `${mock?.counters.good} / ${mock?.objective.shiftTarget}`}</span>
      </div>
    </div>
  );
}
