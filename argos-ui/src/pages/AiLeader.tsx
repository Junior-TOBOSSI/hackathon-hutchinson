import { useState } from 'react';
import { api } from '../api/client';
import { HealthChart } from '../components/charts';
import { Icon, ICONS, Loading, TopBar } from '../components/ui';
import { useApi } from '../hooks/useApi';

const STEPS = ['Photos', 'Labels', 'Entraînement', 'Test', 'Registre', 'Déploiement'];
const tone = (h: number, t: number) => (h < t ? ['var(--red)', 'var(--red-text)'] : h < 90 ? ['var(--amber)', 'var(--amber-text)'] : ['var(--green)', 'var(--green-text)']);

/** Fabrique de modèles : santé, dérives, réentraînement, versions. */
export default function AiLeader() {
  const { data: ai, setData } = useApi(() => api.aiOverview(), [], 30000);
  const [msg, setMsg] = useState('');
  if (!ai) return <Loading />;
  const total = ai.counts.healthy + ai.counts.watch + ai.counts.retrain;
  const setMode = (m: 'MANUEL' | 'AUTO') => api.setRetrainMode(m).then(() => setData({ ...ai, retrainMode: m }));
  const tr = ai.training;

  return (
    <div className="screen">
      <TopBar title="Fabrique de modèles" sub="AI Leader · usine du Chili" />
      <main className="col" style={{ padding: '20px 24px', gap: 18 }}>
        <div className="row stack-mobile" style={{ flexWrap: 'wrap' }}>
          <span className="grow muted" style={{ fontWeight: 600 }}>{msg}</span>
          <span className="muted" style={{ fontWeight: 600 }}>Réentraînement</span>
          <div className="row" style={{ background: '#fff', border: '2px solid var(--line)', borderRadius: 26, padding: 4, gap: 0 }}>
            {(['MANUEL', 'AUTO'] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)} className="btn" style={{ borderRadius: 22, background: ai.retrainMode === m ? 'var(--navy)' : 'transparent', color: ai.retrainMode === m ? '#fff' : 'var(--muted)' }}>{m === 'AUTO' ? 'Auto + validation humaine' : 'Manuel'}</button>
            ))}
          </div>
          <button className="btn btn-primary" style={{ height: 50 }}>+ Entraîner un modèle</button>
        </div>

        <div className="row stack-mobile" style={{ gap: 18, alignItems: 'stretch' }}>
          <div className="card col grow" style={{ gap: 14 }}>
            <div className="between"><h2 className="h2">Santé des modèles en production</h2><span className="muted" style={{ fontSize: 14 }}>{total} modèles · seuil de réentraînement {ai.threshold} %</span></div>
            <div style={{ display: 'flex', height: 30, borderRadius: 8, overflow: 'hidden' }}>
              <div style={{ width: `${(ai.counts.healthy / total) * 100}%`, background: 'var(--green)' }} />
              <div style={{ width: `${(ai.counts.watch / total) * 100}%`, background: 'var(--amber)' }} />
              <div style={{ width: `${(ai.counts.retrain / total) * 100}%`, background: 'var(--red)' }} />
            </div>
            <div className="row" style={{ gap: 28, flexWrap: 'wrap' }}>
              <span><b className="num" style={{ fontSize: 24, color: 'var(--green-text)' }}>{ai.counts.healthy}</b> sains (≥ 90 %)</span>
              <span><b className="num" style={{ fontSize: 24, color: 'var(--amber-text)' }}>{ai.counts.watch}</b> à surveiller</span>
              <span><b className="num" style={{ fontSize: 24, color: 'var(--red-text)' }}>{ai.counts.retrain}</b> à réentraîner (&lt; {ai.threshold} %)</span>
            </div>
            <div className="between"><b>Évolution sur 14 jours · modèles qui décrochent</b><span className="muted" style={{ fontSize: 13 }}>Santé = part des verdicts confirmés par les opérateurs</span></div>
            <HealthChart series={ai.series} threshold={ai.threshold} />
            <div className="row" style={{ gap: 22, flexWrap: 'wrap', fontSize: 14 }}>
              {ai.series.map((s) => <span key={s.name} className="row" style={{ gap: 8 }}><span style={{ width: 18, height: 4, borderRadius: 2, background: s.color }} />{s.name} · {s.values[s.values.length - 1]} %</span>)}
            </div>
          </div>

          <div className="card col" style={{ width: 440, maxWidth: '100%' }}>
            <div className="between"><h2 className="h2">Dérives détectées</h2><span className="muted" style={{ fontSize: 14 }}>{ai.drifts.length} sous le seuil</span></div>
            {ai.drifts.map((d) => (
              <div key={d.modelId} className="col" style={{ gap: 6, padding: '12px 14px', borderRadius: 16, border: '2px solid var(--red)' }}>
                <b>{d.title}</b>
                <span className="muted" style={{ fontSize: 14 }}>{d.detail}</span>
                {d.mode === 'MANUEL'
                  ? <button className="btn btn-primary" onClick={() => api.retrain(d.modelId).then(() => setMsg('Entraînement relancé.'))}>Relancer l’entraînement</button>
                  : <div className="row" style={{ gap: 8 }}><button className="btn btn-dark grow" onClick={() => setMsg('Réentraînement approuvé.')}>Approuver</button><button className="btn btn-ghost grow">Reporter</button></div>}
              </div>
            ))}
          </div>
        </div>

        <div className="card col" style={{ gap: 6, overflowX: 'auto' }}>
          <div className="between"><h2 className="h2">Modèles déployés · par poste et groupe de postes</h2><span className="muted" style={{ fontSize: 14 }}>triés par santé</span></div>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760, fontSize: 15 }}>
            <thead><tr className="muted" style={{ fontSize: 13, textAlign: 'left', letterSpacing: '0.06em' }}><th style={{ padding: '6px 0' }}>MODÈLE</th><th>CAS</th><th>POSTES</th><th>VERSION</th><th style={{ width: 220 }}>SANTÉ</th><th>RAPPEL KO</th><th /></tr></thead>
            <tbody>
              {[...ai.models].sort((a, b) => a.healthPct - b.healthPct).map((m) => {
                const [c, t] = tone(m.healthPct, ai.threshold);
                return (
                  <tr key={m.id} style={{ borderTop: '1px solid #eef2f8' }}>
                    <td style={{ padding: '9px 0', fontWeight: 600 }}>{m.name}</td><td>{m.useCase}</td><td>{m.scope}</td><td>{m.version}</td>
                    <td><div className="row" style={{ gap: 10 }}><div className="track grow" style={{ height: 10, overflow: 'visible' }}><div className="fill" style={{ width: `${m.healthPct}%`, background: c }} /><div style={{ position: 'absolute', left: `${ai.threshold}%`, top: -4, width: 2, height: 18, background: 'var(--navy)' }} /></div><b style={{ width: 44, color: t }}>{m.healthPct} %</b></div></td>
                    <td>{m.recallKoPct ? `${m.recallKoPct} %` : '—'}</td>
                    <td><button className="btn" style={{ background: 'none', color: 'var(--blue)', padding: 0 }} onClick={() => m.healthPct < ai.threshold && api.retrain(m.id).then(() => setMsg(`${m.name} : entraînement relancé.`))}>{m.healthPct < ai.threshold ? 'Réentraîner' : 'Voir'}</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="card col" style={{ gap: 14 }}>
          <div className="between"><h2 className="h2">Entraînement en cours · {tr.modelName} {tr.version}</h2><span className="muted" style={{ fontSize: 14 }}>{tr.dataset}</span></div>
          <div className="row stack-mobile" style={{ gap: 8 }}>
            {STEPS.map((s, i) => {
              const done = i < tr.step, cur = i === tr.step;
              return (
                <div key={s} className="row grow" style={{ height: 52, borderRadius: 14, padding: '0 14px', gap: 10, fontWeight: 700, background: cur ? 'var(--blue)' : done ? 'var(--green-soft)' : 'var(--op-bg)', color: cur ? '#fff' : done ? 'var(--green-text)' : 'var(--muted)' }}>
                  <span style={{ width: 26, height: 26, borderRadius: 13, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, background: cur ? '#fff' : done ? 'var(--green)' : 'var(--track)', color: cur ? 'var(--blue)' : done ? '#fff' : 'var(--muted)' }}>{done ? <Icon d={ICONS.check} size={16} color="#fff" stroke={3} /> : i + 1}</span>{s}
                </div>
              );
            })}
          </div>
          <div className="row stack-mobile" style={{ gap: 28, flexWrap: 'wrap' }}>
            <span>Rappel KO <b className="num" style={{ fontSize: 24, color: 'var(--green-text)' }}>{tr.recallKoPct} %</b> <span className="muted">(avant : {tr.previousRecallKoPct} %)</span></span>
            <span>Joints absents arrêtés <b className="num" style={{ fontSize: 24 }}>{tr.absentStoppedPct} %</b></span>
            <span>Doubles joints arrêtés <b className="num" style={{ fontSize: 24 }}>{tr.doubleStoppedPct} %</b></span>
            <span style={{ flex: 1 }} />
            <button className="btn btn-ghost">Comparer à la version en production</button>
            <button className="btn btn-green" onClick={() => api.promote('m2', tr.version).then(() => setMsg(`${tr.modelName} ${tr.version} promu en production.`))}>Promouvoir en production</button>
          </div>
        </div>
      </main>
    </div>
  );
}
