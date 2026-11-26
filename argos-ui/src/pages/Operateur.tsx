import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, USE_MOCK } from '../api/client';
import type { Scenario } from '../api/mock';
import type { StationLive } from '../api/types';
import { useAuth } from '../auth';
import { HourlyGauges, ProgressRing } from '../components/charts';
import { operatorActions, type OperatorAction } from '../components/priority';
import { Clock, deltaText, fmt, Icon, ICONS, Loading, TopBar } from '../components/ui';
import { useApi } from '../hooks/useApi';

/**
 * Écran du poste. Un seul écran qui s'adapte à l'état reçu :
 * tout va bien · pièce KO · EPI ou poste en défaut · plusieurs problèmes en même temps.
 * En démo : ?scenario=ok|ko|epi|multi
 */
export default function Operateur() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const scenario = (params.get('scenario') as Scenario) || 'ok';
  const stationId = user?.stationId ?? 'A1·P06';
  const { data: live } = useApi(() => api.stationLive(stationId, scenario), [stationId, scenario], 2000);
  const [reported, setReported] = useState(false);

  if (!live) return <Loading />;
  const actions = operatorActions(live);
  const envIssues = live.issues.filter((i) => i.category === 'SECURITE_EPI' || i.category === 'COMPORTEMENT' || i.category === 'POSTE');
  const ko = live.part.verdict === 'KO';
  const multi = ko && envIssues.length > 0;
  const hour = new Date(live.now).getHours();

  const report = async () => { await api.reportProblem(stationId); setReported(true); setTimeout(() => setReported(false), 4000); };

  return (
    <div className="screen" style={{ background: ko || envIssues.length ? 'var(--red-tint)' : 'var(--op-bg)' }}>
      <TopBar title={`POSTE ${live.stationId}`} sub={`Presse injection · ${live.product}`} right={<><span className="sub hide-mobile">Shift {live.shift.code} · {live.shift.start.slice(0, 2)} h – {live.shift.end.slice(0, 2)} h</span><Clock iso={live.now} /></>} />

      {envIssues.length > 0 && <ProblemBanner actions={actions} />}

      <main className="row stack-mobile" style={{ flex: 1, alignItems: 'stretch', gap: 24, padding: '20px 28px 0' }}>
        {/* Colonne gauche : la pièce, ou l'image caméra si seul l'environnement est en défaut */}
        <section className="card-op col" style={{ width: 440, maxWidth: '100%', gap: 14 }}>
          {!ko && envIssues.length > 0 && live.frontSnapshotUrl
            ? <SnapshotPanel live={live} instruction={envIssues[0].instruction} />
            : <PartPanel live={live} />}
        </section>

        <section className="col grow" style={{ gap: 18 }}>
          {multi ? (
            <>
              <MultiCard live={live} actions={actions} />
              <ObjectiveStrip live={live} />
            </>
          ) : (
            <div className="card-op col" style={{ gap: 12, padding: '18px 30px' }}>
              <div className="row stack-mobile" style={{ gap: 30 }}>
                <ProgressRing value={live.counters.good} target={live.objective.shiftTarget} expected={live.objective.expectedNow} />
                <div className="col grow" style={{ gap: 16 }}>
                  <span className="label-caps" style={{ fontSize: 18 }}>Objectif du shift</span>
                  <div>
                    <div className="num" style={{ fontSize: 64 }}>{fmt(live.objective.shiftTarget - live.counters.good)}</div>
                    <div className="muted" style={{ fontSize: 18, fontWeight: 600 }}>pièces à faire</div>
                  </div>
                  <div className="row">
                    <MiniStat value={deltaText(live.counters.good - live.objective.expectedNow, true)} tone={live.counters.good >= live.objective.expectedNow ? 'green' : 'red'} />
                    <MiniStat value={`${live.counters.ko} pièces KO`} tone={ko ? 'red' : 'grey'} />
                  </div>
                  <span className="muted" style={{ fontSize: 14 }}>Trait noir : où vous devriez être maintenant ({live.objective.expectedNow})</span>
                </div>
              </div>
              <HourlyGauges hours={live.hourly} perHour={live.objective.perHour} currentHour={hour} height={ko ? 48 : 56} />
            </div>
          )}

          <div className="grid-3">
            <StatusTile ok={live.checks.securite} icon={live.checks.securite ? ICONS.shield : ICONS.shieldAlert} okTitle="Sécurité OK" okSub="EPI portés" koTitle="Sécurité" koSub={envIssues.find((i) => i.category !== 'POSTE')?.label ?? ''} />
            <StatusTile ok={live.checks.poste} icon={ICONS.grid} okTitle="Poste rangé" okSub="Rien qui traîne" koTitle="Poste" koSub={envIssues.find((i) => i.category === 'POSTE')?.label ?? ''} />
            <StatusTile ok icon={ICONS.check} okTitle={ko ? 'Qualité' : 'Qualité OK'} okSub={`Taux KO ${live.checks.koRatePct.toLocaleString('fr-FR')} %`} koTitle="" koSub="" />
          </div>

          <button onClick={report} className="cond" style={{ height: 88, border: 'none', borderRadius: 26, background: reported ? 'var(--navy)' : 'var(--primary)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 18, fontWeight: 700, fontSize: 36, letterSpacing: '0.06em' }}>
            <Icon d={ICONS.flag} size={40} color="#fff" />
            {reported ? 'SUPERVISEUR PRÉVENU' : 'SIGNALER UN PROBLÈME'}
          </button>
        </section>
      </main>

      <footer className="between muted" style={{ height: 40, alignItems: 'center', padding: '0 28px', fontSize: 13 }}>
        <span>Visage flouté · aucune vidéo enregistrée</span>
        <span>Caméra pièce {live.partCameraOnline ? 'en ligne' : 'hors ligne'} · modèle qualité {live.qualityModelVersion}</span>
      </footer>

      {USE_MOCK && <ScenarioSwitcher value={scenario} onChange={(s) => setParams({ scenario: s })} />}
    </div>
  );
}

function ProblemBanner({ actions }: { actions: OperatorAction[] }) {
  return (
    <div className="row" style={{ background: 'var(--red)', color: '#fff', padding: '12px 28px', flexWrap: 'wrap', gap: 14 }}>
      <Icon d={ICONS.warn} size={32} color="#fff" stroke={2.2} />
      {actions.length > 1 ? (
        <>
          <span className="cond" style={{ fontWeight: 700, fontSize: 28, letterSpacing: '0.04em' }}>{actions.length} PROBLÈMES</span>
          {actions.map((a, i) => (
            <span key={a.key} style={{ padding: '6px 12px', borderRadius: 14, background: a.strong ? '#fff' : 'rgba(255,255,255,.85)', color: 'var(--red-text)', fontSize: 16, fontWeight: 700 }}>{i + 1} · {a.title}</span>
          ))}
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 14 }}>la sécurité d’abord</span>
        </>
      ) : (
        <>
          <span className="cond" style={{ fontWeight: 700, fontSize: 30, letterSpacing: '0.04em' }}>{actions[0]?.title.toUpperCase()}</span>
          <span style={{ fontSize: 18 }}>Le voyant repassera au vert tout seul.</span>
        </>
      )}
    </div>
  );
}

function PartPanel({ live }: { live: StationLive }) {
  const ko = live.part.verdict === 'KO';
  const c = ko ? 'var(--red)' : 'var(--green)';
  return (
    <>
      <span className="label-caps" style={{ textAlign: 'center', fontSize: 18 }}>Pièce en cours · n° {live.part.number}</span>
      <div style={{ height: ko ? 250 : 270, borderRadius: 18, overflow: 'hidden', border: `5px solid ${c}`, flexShrink: 0 }}>
        <img src={live.part.imageUrl} alt={ko ? `Pièce non conforme : ${live.part.jointsDetected} joints détectés, zone en défaut entourée de rouge` : 'Pièce conforme : un seul joint détecté'} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
      </div>
      <div style={{ flex: 1, minHeight: 120, borderRadius: 20, background: c, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 22, padding: '0 20px' }}>
        <span className="num" style={{ fontSize: 96, lineHeight: 0.9 }}>{ko ? 'KO' : 'OK'}</span>
        <span style={{ fontSize: 18, fontWeight: 600, lineHeight: 1.3 }}>
          {ko ? <>{live.part.jointsDetected === 0 ? 'Joint absent' : `${live.part.jointsDetected} joints détectés`}<br />Posez la pièce dans le bac rebuts</> : <>1 joint bleu détecté<br />Le cycle est parti</>}
        </span>
      </div>
    </>
  );
}

function SnapshotPanel({ live, instruction }: { live: StationLive; instruction: string }) {
  const t = new Date(live.now);
  return (
    <>
      <span className="label-caps" style={{ textAlign: 'center', fontSize: 18 }}>Ce que la caméra a vu · {String(t.getHours()).padStart(2, '0')}:{String(t.getMinutes()).padStart(2, '0')}</span>
      <div style={{ borderRadius: 18, overflow: 'hidden', border: '5px solid var(--red)', lineHeight: 0 }}>
        <img src={live.frontSnapshotUrl} alt="Image de la caméra frontale, visage flouté, manquement encadré en rouge" style={{ width: '100%', display: 'block' }} />
      </div>
      <div className="col" style={{ flex: 1, justifyContent: 'center', gap: 6, borderRadius: 20, background: 'var(--red-bg)', border: '2px solid var(--red-light)', padding: '14px 20px' }}>
        <span className="cond" style={{ fontWeight: 700, fontSize: 30, color: 'var(--red-text)' }}>{instruction}</span>
        <span style={{ fontSize: 16, color: 'var(--red-dark)' }}>Le cadre rouge montre ce qui manque. Le voyant repasse au vert tout seul.</span>
      </div>
    </>
  );
}

function MultiCard({ live, actions }: { live: StationLive; actions: OperatorAction[] }) {
  return (
    <div className="card-op row stack-mobile" style={{ flex: 1, border: '3px solid var(--red)', padding: '16px 20px', gap: 18, alignItems: 'stretch' }}>
      <div className="col" style={{ width: 340, maxWidth: '100%', flexShrink: 0, gap: 8 }}>
        <span className="label-caps">Ce que la caméra a vu</span>
        {live.frontSnapshotUrl && <img src={live.frontSnapshotUrl} alt="Image caméra frontale, visage flouté, manquements encadrés en rouge" style={{ width: '100%', borderRadius: 14 }} />}
      </div>
      <ol className="col grow" style={{ justifyContent: 'center', gap: 14, margin: 0, padding: 0, listStyle: 'none' }}>
        {actions.map((a, i) => (
          <li key={a.key} className="row" style={{ alignItems: 'flex-start' }}>
            <span style={{ width: 34, height: 34, borderRadius: 17, background: a.strong ? 'var(--red)' : 'var(--red-light)', color: a.strong ? '#fff' : 'var(--red-dark)', fontWeight: 700, fontSize: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{i + 1}</span>
            <div><div className="cond" style={{ fontWeight: 700, fontSize: 24, color: a.strong ? 'var(--red-text)' : 'var(--ink)' }}>{a.title}</div><div className="muted" style={{ fontSize: 14 }}>{a.subtitle}</div></div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function ObjectiveStrip({ live }: { live: StationLive }) {
  const { good } = live.counters, { shiftTarget, expectedNow } = live.objective;
  return (
    <div className="card-op row" style={{ padding: '12px 20px', gap: 18, borderRadius: 20 }}>
      <span className="label-caps" style={{ fontSize: 15 }}>Objectif</span>
      <span className="num" style={{ fontSize: 30, color: 'var(--green-text)' }}>{good} <span className="muted" style={{ fontSize: 18 }}>/ {fmt(shiftTarget)}</span></span>
      <div className="track grow" style={{ height: 12 }}><div className="fill" style={{ width: `${(good / shiftTarget) * 100}%`, background: 'var(--green)' }} /></div>
      <span style={{ fontSize: 15, fontWeight: 600 }}>{shiftTarget - good} à faire</span>
      <span style={{ fontSize: 15, fontWeight: 700, color: good >= expectedNow ? 'var(--green-text)' : 'var(--red-text)' }}>{deltaText(good - expectedNow, true)}</span>
    </div>
  );
}

function MiniStat({ value, tone }: { value: string; tone: 'green' | 'red' | 'grey' }) {
  const bg = tone === 'green' ? 'var(--green-soft)' : tone === 'red' ? 'var(--red-soft)' : 'var(--op-bg)';
  const fg = tone === 'green' ? 'var(--green-text)' : tone === 'red' ? 'var(--red-text)' : 'var(--ink)';
  return <span className="cond" style={{ background: bg, color: fg, borderRadius: 16, padding: '10px 16px', fontWeight: 700, fontSize: 24 }}>{value}</span>;
}

function StatusTile({ ok, icon, okTitle, okSub, koTitle, koSub }: { ok: boolean; icon: string; okTitle: string; okSub: string; koTitle: string; koSub: string }) {
  return (
    <div className="row" style={{ background: '#fff', borderRadius: 20, padding: ok ? '14px 18px' : '11px 15px', border: ok ? 'none' : '3px solid var(--red)', gap: 14 }}>
      <span style={{ width: 48, height: 48, borderRadius: 24, background: ok ? 'var(--green)' : 'var(--red)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Icon d={icon} size={26} color="#fff" stroke={2.4} /></span>
      <div>
        <div className="cond" style={{ fontWeight: 700, fontSize: 22, color: ok ? 'var(--ink)' : 'var(--red-text)' }}>{ok ? okTitle : koTitle}</div>
        <div style={{ fontSize: 14, color: ok ? 'var(--muted)' : 'var(--red-dark)' }}>{ok ? okSub : koSub}</div>
      </div>
    </div>
  );
}

function ScenarioSwitcher({ value, onChange }: { value: Scenario; onChange: (s: Scenario) => void }) {
  const opts: [Scenario, string][] = [['ok', 'Tout va bien'], ['ko', 'Pièce KO'], ['epi', 'EPI manquant'], ['multi', 'Plusieurs problèmes']];
  return (
    <div style={{ position: 'fixed', left: '50%', transform: 'translateX(-50%)', bottom: 4, background: 'var(--navy)', color: '#fff', borderRadius: 12, padding: 4, display: 'flex', gap: 4, boxShadow: '0 8px 24px rgba(0,0,0,.3)', fontSize: 12 }}>
      <span style={{ alignSelf: 'center', padding: '0 6px', color: 'var(--on-navy-muted)' }}>Démo</span>
      {opts.map(([k, l]) => (
        <button key={k} onClick={() => onChange(k)} style={{ border: 'none', borderRadius: 9, padding: '5px 9px', fontWeight: 700, background: value === k ? 'var(--primary)' : 'transparent', color: '#fff' }}>{l}</button>
      ))}
    </div>
  );
}
