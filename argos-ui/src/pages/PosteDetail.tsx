import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { StationDetail } from '../api/types';
import { Kpi, Loading, TopBar, deltaText } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { industrial, LIVE_INDUSTRIAL } from '../api/industrial';
import { clockTime, detailView } from '../api/industrial-view';

type DetailDisplay = Omit<StationDetail, 'product' | 'efficiencyPct' | 'good' | 'expectedNow' | 'delta' | 'ratePerHour' | 'koRatePct' | 'koByDefect' | 'lanes' | 'epiCounts' | 'events'> & {
  product: string | null; efficiencyPct: number | null; good: number | null; expectedNow: number | null;
  delta: number | null; ratePerHour: number | null; koRatePct: number | null;
  koByDefect: { absent: number | null; double: number | null };
  lanes: StationDetail['lanes'] | null;
  epiCounts: { label: string; count: number | null }[];
  events: { time: string; category: 'EPI' | 'COMPORTEMENT' | 'POSTE' | 'SAFETY'; label: string; detail: string; shift: string }[];
};

/** Détail d'un poste pour le superviseur : indicateurs du poste, jamais de la personne. Aucune image. */
export default function PosteDetail() {
  const { id = 'A1·P06' } = useParams();
  const navigate = useNavigate();
  const { data: stations } = useApi(() => LIVE_INDUSTRIAL ? industrial.stations() : Promise.resolve([]), [], LIVE_INDUSTRIAL ? 5000 : 0);
  const { data: mock } = useApi(() => LIVE_INDUSTRIAL ? Promise.resolve(null) : api.stationDetail(id), [id], LIVE_INDUSTRIAL ? 0 : 15000);
  const { data: real, error } = useApi(() => LIVE_INDUSTRIAL ? detailView(id) : Promise.resolve(null), [id], LIVE_INDUSTRIAL ? 5000 : 0);
  const current = real?.station.station_id === id ? real : null;
  if (LIVE_INDUSTRIAL && !current && !error || !LIVE_INDUSTRIAL && !mock) return <Loading />;
  const shift = current?.station.current_shift;
  const shiftStart = shift ? new Date(shift.shift.started_at).getTime() : null;
  const shiftMinutes = shift?.shift.planned_duration_min ?? 480;
  const labels = ['Lunettes absentes', 'Gants absents', 'Casque absent', 'Chaussures de sécurité', 'Téléphone à la main', 'Main près de la presse', 'Zone interdite'];
  const d: DetailDisplay | null = LIVE_INDUSTRIAL && current ? {
    stationId: id, product: null,
    efficiencyPct: shift?.kpi.efficiency == null ? null : shift.kpi.efficiency * 100,
    good: current.kpi.ok_parts, expectedNow: shift?.kpi.expected_ok_parts_by_now ?? null,
    delta: shift?.kpi.expected_ok_parts_by_now == null ? null : current.kpi.ok_parts - shift.kpi.expected_ok_parts_by_now,
    ratePerHour: current.kpi.actual_total_rate_per_hour, ko: current.kpi.nok_parts,
    koRatePct: current.kpi.nok_rate == null ? null : current.kpi.nok_rate * 100,
    koByDefect: { absent: null, double: null },
    lanes: shiftStart == null ? null : ['Sécurité', 'Poste', 'Qualité', 'Rythme'].map((name) => ({
      name, soft: name === 'Rythme', episodes: current.alerts.filter((alert) => name === 'Sécurité' ? alert.use_case === 'safety' : name === 'Poste' ? alert.use_case === 'workstation' : name === 'Qualité' ? alert.use_case === 'quality' : false).map((alert) => [Math.max(0, (new Date(alert.first_seen_at).getTime() - shiftStart) / 60000), Math.min(shiftMinutes, (new Date(alert.last_seen_at).getTime() - shiftStart) / 60000)] as [number, number]).filter(([a, b]) => b >= a && a <= shiftMinutes),
    })),
    epiCounts: labels.map((label) => ({ label, count: null })),
    events: current.alerts.filter((alert) => alert.use_case === 'safety' || alert.use_case === 'workstation').map((alert) => ({
      time: clockTime(alert.last_seen_at), category: alert.use_case === 'workstation' ? 'POSTE' as const : alert.alert_type.startsWith('behavior.') ? 'COMPORTEMENT' as const : alert.alert_type.startsWith('ppe.') ? 'EPI' as const : 'SAFETY' as const,
      label: alert.title, detail: `${alert.occurrences} observation(s) · ${alert.status}${alert.simulated ? ' · synthétique' : ''}`, shift: shift?.shift.name ?? 'inconnu',
    })),
  } : mock;
  const SHIFT_MIN = LIVE_INDUSTRIAL ? shiftMinutes : 480;

  return (
    <div className="screen">
      <TopBar title={<>Poste {d?.stationId ?? id}</>} sub={d?.product ?? 'Produit non renseigné'} right={<Link to="/superviseur" style={{ color: 'var(--on-navy-muted)', fontWeight: 600 }}>← Atelier</Link>} />
      <main className="col" style={{ padding: '20px 24px', gap: 16 }}>
        {LIVE_INDUSTRIAL && <div className="row" style={{ gap: 12 }}><label>Poste <select className="btn" value={id} onChange={(event) => navigate(`/superviseur/poste/${encodeURIComponent(event.target.value)}`)}>{stations?.map((station) => <option key={station.station_id} value={station.station_id}>{station.station_id}</option>)}</select></label>{error && <span style={{ color: 'var(--red-text)' }}>Connexion interrompue · dernières données reçues : {error}</span>}</div>}
        {!d && <div className="card">Données industrielles indisponibles : {error}</div>}
        {d && <>
        <div className="row" style={{ flexWrap: 'wrap', gap: 10 }}>
          {(LIVE_INDUSTRIAL ? ['Shift précédent · indisponible', `Shift ${shift?.shift.name ?? 'inconnu'}`, 'Shift suivant · indisponible', 'Journée · données indisponibles'] : ['Shift A · 5 h – 13 h', 'Shift B · en cours', 'Shift C · 21 h – 5 h', 'Journée']).map((s, i) => (
            <span key={s} className="pill" style={{ padding: '10px 18px', borderRadius: 22, fontSize: 15, background: i === 1 ? 'var(--navy)' : '#fff', color: i === 1 ? '#fff' : 'var(--muted)', border: i === 1 ? 'none' : '2px solid var(--line)' }}>{s}</span>
          ))}
          <span style={{ flex: 1 }} />
          <span className="muted" style={{ fontSize: 14 }}>Indicateurs du poste : opérateur, machine et environnement ensemble, sans nom ni classement</span>
        </div>

        <div className="grid-5">
          <Kpi label="Efficience" value={d.efficiencyPct == null ? '—' : `${d.efficiencyPct.toLocaleString('fr-FR')} %`} sub={d.expectedNow == null ? 'Objectif indisponible' : `${d.good} pièces bonnes / ${Math.round(d.expectedNow)} attendues`} />
          <Kpi label="Rythme" value={d.delta == null ? '—' : deltaText(d.delta, true)} valueStyle={{ fontSize: 30, color: d.delta != null && d.delta < 0 ? 'var(--red-text)' : 'var(--green-text)' }} sub={d.ratePerHour == null ? 'Cadence indisponible' : LIVE_INDUSTRIAL ? `${Math.round(d.ratePerHour)} pièces / h` : `${d.ratePerHour} pièces / h depuis 15 h`} />
          <Kpi label="Pièces KO" value={d.ko} sub={`joint absent ${d.koByDefect.absent ?? 'inconnu'} · double joint ${d.koByDefect.double ?? 'inconnu'}`} />
          <Kpi label="Taux de KO" value={d.koRatePct == null ? '—' : `${d.koRatePct.toLocaleString('fr-FR')} %`} sub={LIVE_INDUSTRIAL ? '8 dernières heures' : 'moyenne cellule 1,7 %'} />
          <Kpi label="Événements sécurité" value={LIVE_INDUSTRIAL ? current?.alerts.filter((alert) => alert.use_case === 'safety').reduce((sum, alert) => sum + alert.occurrences, 0) ?? '—' : d.events.filter((e) => e.category !== 'POSTE').length} valueStyle={{ color: 'var(--red)' }} sub={LIVE_INDUSTRIAL ? 'Observations enregistrées, dont synthétiques' : d.epiCounts.filter((e) => e.count).map((e) => `${e.label.toLowerCase()} ${e.count}`).join(' · ')} />
        </div>

        <div className="card col" style={{ gap: 10 }}>
          <div className="between"><h2 className="h2">Bande du shift</h2><span className="muted" style={{ fontSize: 14 }}>{LIVE_INDUSTRIAL ? 'Épisodes enregistrés · une absence de trait ne confirme pas la conformité' : 'Chaque trait rouge est un épisode · le reste du temps, tout était vert'}</span></div>
          {d.lanes?.map((l) => (
            <div key={l.name} className="row" style={{ gap: 14 }}>
              <span style={{ width: 92, fontWeight: 600 }}>{l.name}</span>
              <div className="track grow" style={{ height: 26, borderRadius: 8 }}>
                <div className="fill" style={{ width: `${LIVE_INDUSTRIAL ? 0 : (282 / SHIFT_MIN) * 100}%`, background: 'var(--green-pale)', borderRadius: 0 }} />
                {l.episodes.map(([a, b], i) => (
                  <div key={i} style={{ position: 'absolute', top: 0, bottom: 0, left: `${(a / SHIFT_MIN) * 100}%`, width: `${Math.max(0.6, ((b - a) / SHIFT_MIN) * 100)}%`, background: l.soft ? 'var(--red-light)' : 'var(--red)' }} />
                ))}
              </div>
            </div>
          ))}
          {!d.lanes && <div className="muted">Bande du shift indisponible : aucun shift actif connu.</div>}
          <div className="row" style={{ gap: 14 }}>
            <span style={{ width: 92 }} />
            <div className="between grow muted" style={{ fontSize: 13 }}>{LIVE_INDUSTRIAL ? <span>{shift ? `${clockTime(shift.shift.started_at)} → ${clockTime(shift.shift.planned_end_at)}` : 'Période indisponible'}</span> : [13, 14, 15, 16, 17, 18, 19, 20, 21].map((h) => <span key={h}>{h} h</span>)}</div>
          </div>
        </div>

        <div className="grid-2">
          <div className="card col" style={{ gap: 4 }}>
            <h2 className="h2" style={{ marginBottom: 6 }}>EPI et comportements · aujourd’hui</h2>
            {d.epiCounts.map((e) => (
              <div key={e.label} className="row" style={{ padding: '8px 0', borderBottom: '1px solid var(--line-soft)' }}>
                <span className="grow">{e.label}</span>
                <span className={`pill ${e.count == null ? 'pill-amber' : e.count ? 'pill-red' : 'pill-green'} num`} style={{ fontSize: 18, minWidth: 34, textAlign: 'center' }}>{e.count ?? '—'}</span>
              </div>
            ))}
          </div>
          <div className="card col" style={{ gap: 10 }}>
            <div className="between"><h2 className="h2">Alertes EPI et poste · {LIVE_INDUSTRIAL ? 'historique disponible' : 'shift B'}</h2><span className="muted" style={{ fontSize: 13 }}>Pour information · aucune validation demandée</span></div>
            {d.events.map((e, i) => {
              const red = e.category !== 'POSTE' && i < 3;
              return (
                <div key={i} className="col" style={{ gap: 4, padding: '12px 14px', borderRadius: 14, border: `2px solid ${red ? 'var(--red)' : 'var(--line)'}` }}>
                  <div className="row" style={{ gap: 10 }}>
                    <span className="cond" style={{ fontWeight: 700, fontSize: 22, color: 'var(--primary)' }}>{d.stationId}</span>
                    <span className="cond muted" style={{ fontWeight: 700, fontSize: 22 }}>{e.time}</span>
                    <span className={`pill ${red ? 'pill-red' : 'pill-blue'}`}>{e.category === 'EPI' ? 'EPI' : e.category === 'COMPORTEMENT' ? 'Comportement' : e.category === 'SAFETY' ? 'Sécurité non précisée' : 'Poste de travail'}</span>
                    <span style={{ flex: 1 }} />
                    <span className="muted" style={{ fontSize: 13 }}>Shift {e.shift}</span>
                  </div>
                  <span style={{ fontSize: 15, fontWeight: 700 }}>{e.label}</span>
                  <span className="muted" style={{ fontSize: 14 }}>{e.detail}</span>
                </div>
              );
            })}
          </div>
        </div>
        {LIVE_INDUSTRIAL && <div className="grid-2"><div className="card col"><h2 className="h2">Pièces récentes · maximum 100</h2>{current?.parts.map((part) => <span key={part.part_id}>{clockTime(part.created_at)} · {part.cycle_id} · {part.effective_verdict}</span>)}</div><div className="card col"><h2 className="h2">Événements récents · maximum 100</h2>{current?.events.map((event) => <span key={event.event_id}>{clockTime(event.occurred_at)} · {event.event_type}</span>)}</div></div>}
        </>}
      </main>
    </div>
  );
}
