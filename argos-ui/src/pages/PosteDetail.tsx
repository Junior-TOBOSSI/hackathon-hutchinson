import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { Kpi, Loading, TopBar, deltaText, fmt } from '../components/ui';
import { useApi } from '../hooks/useApi';

/**
 * Historique d'un poste pour le team leader, sur le shift EN COURS : indicateurs du poste,
 * jamais de la personne. Aucune image. Chaque information n'apparaît qu'une fois :
 * production (rythme), qualité (NOK), sécurité (événements) ; puis la bande du shift et la
 * liste des événements.
 */
export default function PosteDetail() {
  const { id = 'C3·P06' } = useParams();
  const { data: d } = useApi(() => api.stationDetail(id), [id], 15000);
  if (!d) return <Loading />;
  const shift = d.shift ?? { code: 'B' as const, start: '13:00', end: '21:00' };
  const start = Number(shift.start.slice(0, 2));
  const hours = Array.from({ length: 9 }, (_, i) => (start + i) % 24);
  const SHIFT_MIN = 480;
  const elapsed = Math.min(SHIFT_MIN, d.elapsedMin ?? 282);
  const safety = d.events.filter((e) => e.category !== 'POSTE');
  const counted = d.epiCounts.filter((e) => e.count > 0);

  return (
    <div className="screen">
      <TopBar
        title={<>Poste {id} · historique</>}
        sub={d.product}
        right={<>
          <Link to={`/team-leader/poste/${encodeURIComponent(id)}`} className="chip" style={{ color: '#fff', fontWeight: 600 }}>Écran du poste</Link>
          <Link to="/team-leader" className="chip" style={{ color: '#fff', fontWeight: 600 }}>← Ma cellule</Link>
        </>}
      />
      <main className="col" style={{ padding: '20px 24px', gap: 16 }}>
        <div className="row" style={{ flexWrap: 'wrap', gap: 10 }}>
          <span className="pill" style={{ padding: '10px 18px', borderRadius: 22, fontSize: 15, background: 'var(--navy)', color: '#fff' }}>
            Shift {shift.code} · {start} h – {Number(shift.end.slice(0, 2))} h · en cours
          </span>
          <span style={{ flex: 1 }} />
          <span className="muted" style={{ fontSize: 14 }}>Indicateurs du poste : opérateur, machine et environnement ensemble, sans nom ni classement</span>
        </div>

        <div className="grid-3">
          <Kpi label="Production" value={deltaText(d.delta, true)} valueStyle={{ fontSize: 30, color: d.delta < 0 ? 'var(--red-text)' : 'var(--green-text)' }}
            sub={`${fmt(d.good)} pièces bonnes pour ${fmt(d.expectedNow)} attendues (${d.efficiencyPct.toLocaleString('fr-FR')} %) · ${d.ratePerHour} pièces / h`} />
          <Kpi label="Pièces NOK" value={<>{d.ko} <span className="muted" style={{ fontSize: 20, fontWeight: 600 }}>· {d.koRatePct.toLocaleString('fr-FR')} %</span></>}
            sub={`joint absent ${d.koByDefect.absent} · double joint ${d.koByDefect.double}`} />
          <Kpi label="Événements sécurité" value={safety.length} valueStyle={{ color: safety.length ? 'var(--red)' : 'var(--green-text)' }}
            sub={counted.length ? counted.map((e) => `${e.label.toLowerCase()} ${e.count}`).join(' · ') : 'aucun sur ce shift'} />
        </div>

        <div className="card col" style={{ gap: 10 }}>
          <div className="between"><h2 className="h2">Bande du shift</h2><span className="muted" style={{ fontSize: 14 }}>Chaque trait rouge est un épisode · le reste du temps, tout était vert</span></div>
          {d.lanes.map((l) => (
            <div key={l.name} className="row" style={{ gap: 14 }}>
              <span style={{ width: 92, fontWeight: 600 }}>{l.name}</span>
              <div className="track grow" style={{ height: 26, borderRadius: 8 }}>
                <div className="fill" style={{ width: `${(elapsed / SHIFT_MIN) * 100}%`, background: 'var(--green-pale)', borderRadius: 0 }} />
                {l.episodes.map(([a, b], i) => (
                  <div key={i} style={{ position: 'absolute', top: 0, bottom: 0, left: `${(a / SHIFT_MIN) * 100}%`, width: `${Math.max(0.6, ((b - a) / SHIFT_MIN) * 100)}%`, background: l.soft ? 'var(--red-light)' : 'var(--red)' }} />
                ))}
              </div>
            </div>
          ))}
          <div className="row" style={{ gap: 14 }}>
            <span style={{ width: 92 }} />
            <div className="between grow muted" style={{ fontSize: 13 }}>{hours.map((h, i) => <span key={i}>{h} h</span>)}</div>
          </div>
        </div>

        <div className="card col" style={{ gap: 10 }}>
          <div className="between"><h2 className="h2">Événements EPI et poste · shift {shift.code}</h2><span className="muted" style={{ fontSize: 13 }}>Pour information · aucune validation demandée</span></div>
          {!d.events.length && <span className="muted" style={{ padding: '8px 0' }}>Aucun événement sur ce shift : EPI portés, poste rangé.</span>}
          {d.events.map((e, i) => (
            <div key={i} className="row" style={{ gap: 14, padding: '10px 4px', borderTop: i ? '1px solid var(--line-soft)' : 'none' }}>
              <span className="cond" style={{ fontWeight: 700, fontSize: 20, width: 60 }}>{e.time}</span>
              <span className={`pill ${e.category === 'POSTE' ? 'pill-blue' : 'pill-red'}`} style={{ minWidth: 120, textAlign: 'center' }}>{e.category === 'EPI' ? 'EPI' : e.category === 'COMPORTEMENT' ? 'Comportement' : 'Poste de travail'}</span>
              <span className="grow" style={{ fontWeight: 600 }}>{e.label}</span>
              <span className="muted" style={{ fontSize: 14 }}>{e.detail}</span>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
