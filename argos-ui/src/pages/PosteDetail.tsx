import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { Kpi, Loading, TopBar, deltaText } from '../components/ui';
import { useApi } from '../hooks/useApi';

/** Historique d'un poste pour le team leader : indicateurs du poste, jamais de la personne. Aucune image. */
export default function PosteDetail() {
  const { id = 'C3·P06' } = useParams();
  const { data: d } = useApi(() => api.stationDetail(id), [id], 15000);
  if (!d) return <Loading />;
  const SHIFT_MIN = 480;

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
          {['Shift A · 5 h – 13 h', 'Shift B · en cours', 'Shift C · 21 h – 5 h', 'Journée'].map((s, i) => (
            <span key={s} className="pill" style={{ padding: '10px 18px', borderRadius: 22, fontSize: 15, background: i === 1 ? 'var(--navy)' : '#fff', color: i === 1 ? '#fff' : 'var(--muted)', border: i === 1 ? 'none' : '2px solid var(--line)' }}>{s}</span>
          ))}
          <span style={{ flex: 1 }} />
          <span className="muted" style={{ fontSize: 14 }}>Indicateurs du poste : opérateur, machine et environnement ensemble, sans nom ni classement</span>
        </div>

        <div className="grid-5">
          <Kpi label="Efficience" value={`${d.efficiencyPct.toLocaleString('fr-FR')} %`} sub={`${d.good} pièces bonnes / ${d.expectedNow} attendues`} />
          <Kpi label="Rythme" value={deltaText(d.delta, true)} valueStyle={{ fontSize: 30, color: d.delta < 0 ? 'var(--red-text)' : 'var(--green-text)' }} sub={`${d.ratePerHour} pièces / h depuis 15 h`} />
          <Kpi label="Pièces KO" value={d.ko} sub={`joint absent ${d.koByDefect.absent} · double joint ${d.koByDefect.double}`} />
          <Kpi label="Taux de KO" value={`${d.koRatePct.toLocaleString('fr-FR')} %`} sub="moyenne cellule 1,7 %" />
          <Kpi label="Événements sécurité" value={d.events.filter((e) => e.category !== 'POSTE').length} valueStyle={{ color: 'var(--red)' }} sub={d.epiCounts.filter((e) => e.count).map((e) => `${e.label.toLowerCase()} ${e.count}`).join(' · ')} />
        </div>

        <div className="card col" style={{ gap: 10 }}>
          <div className="between"><h2 className="h2">Bande du shift</h2><span className="muted" style={{ fontSize: 14 }}>Chaque trait rouge est un épisode · le reste du temps, tout était vert</span></div>
          {d.lanes.map((l) => (
            <div key={l.name} className="row" style={{ gap: 14 }}>
              <span style={{ width: 92, fontWeight: 600 }}>{l.name}</span>
              <div className="track grow" style={{ height: 26, borderRadius: 8 }}>
                <div className="fill" style={{ width: `${(282 / SHIFT_MIN) * 100}%`, background: 'var(--green-pale)', borderRadius: 0 }} />
                {l.episodes.map(([a, b], i) => (
                  <div key={i} style={{ position: 'absolute', top: 0, bottom: 0, left: `${(a / SHIFT_MIN) * 100}%`, width: `${Math.max(0.6, ((b - a) / SHIFT_MIN) * 100)}%`, background: l.soft ? 'var(--red-light)' : 'var(--red)' }} />
                ))}
              </div>
            </div>
          ))}
          <div className="row" style={{ gap: 14 }}>
            <span style={{ width: 92 }} />
            <div className="between grow muted" style={{ fontSize: 13 }}>{[13, 14, 15, 16, 17, 18, 19, 20, 21].map((h) => <span key={h}>{h} h</span>)}</div>
          </div>
        </div>

        <div className="grid-2">
          <div className="card col" style={{ gap: 4 }}>
            <h2 className="h2" style={{ marginBottom: 6 }}>EPI et comportements · aujourd’hui</h2>
            {d.epiCounts.map((e) => (
              <div key={e.label} className="row" style={{ padding: '8px 0', borderBottom: '1px solid var(--line-soft)' }}>
                <span className="grow">{e.label}</span>
                <span className={`pill ${e.count ? 'pill-red' : 'pill-green'} num`} style={{ fontSize: 18, minWidth: 34, textAlign: 'center' }}>{e.count}</span>
              </div>
            ))}
          </div>
          <div className="card col" style={{ gap: 10 }}>
            <div className="between"><h2 className="h2">Alertes EPI et poste · shift B</h2><span className="muted" style={{ fontSize: 13 }}>Pour information · aucune validation demandée</span></div>
            {d.events.map((e, i) => {
              const red = e.category !== 'POSTE' && i < 3;
              return (
                <div key={i} className="col" style={{ gap: 4, padding: '12px 14px', borderRadius: 14, border: `2px solid ${red ? 'var(--red)' : 'var(--line)'}` }}>
                  <div className="row" style={{ gap: 10 }}>
                    <span className="cond" style={{ fontWeight: 700, fontSize: 22, color: 'var(--primary)' }}>{id}</span>
                    <span className="cond muted" style={{ fontWeight: 700, fontSize: 22 }}>{e.time}</span>
                    <span className={`pill ${red ? 'pill-red' : 'pill-blue'}`}>{e.category === 'EPI' ? 'EPI' : e.category === 'COMPORTEMENT' ? 'Comportement' : 'Poste de travail'}</span>
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
      </main>
    </div>
  );
}
