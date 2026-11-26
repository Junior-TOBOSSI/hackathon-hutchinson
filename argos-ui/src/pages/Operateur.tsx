import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, USE_MOCK } from '../api/client';
import type { Scenario } from '../api/mock';
import type { StationLive } from '../api/types';
import { useAuth } from '../auth';
import { HourlyGauges, ProgressRing, type ShiftGaugeInput } from '../components/charts';
import { operatorActions, type OperatorAction } from '../components/priority';
import { Clock, deltaText, fmt, Icon, ICONS, Loading, TopBar } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { industrial, LIVE_INDUSTRIAL, type Station } from '../api/industrial';
import { operatorView, type OperatorView } from '../api/industrial-view';

function shiftTimeline(view: OperatorView): ShiftGaugeInput | null {
  if (view.shiftWindow) return {
    startedAt: view.shiftWindow.startedAt, plannedEndAt: view.shiftWindow.plannedEndAt,
    endedAt: view.shiftWindow.endedAt, status: view.shiftWindow.status,
    target: view.shiftWindow.target, actualGood: view.shiftWindow.actualGood, now: view.shiftWindow.now ?? view.now,
  };
  if (!view.shift) return null;
  const at = (time: string) => {
    const date = new Date(view.now);
    const [hour, minute] = time.split(':').map(Number);
    date.setHours(hour, minute, 0, 0);
    return date;
  };
  const start = at(view.shift.start);
  const end = at(view.shift.end);
  if (end <= start) end.setDate(end.getDate() + 1);
  return { startedAt: start.toISOString(), plannedEndAt: end.toISOString(), now: view.now,
    status: 'OPEN', target: view.objective.shiftTarget, actualGood: view.counters.good };
}

/**
 * Écran du poste. Un seul écran qui s'adapte à l'état reçu :
 * tout va bien · pièce KO · EPI ou poste en défaut · plusieurs problèmes en même temps.
 * En démo : ?scenario=ok|ko|epi|multi
 */
export default function Operateur() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const scenario = (params.get('scenario') as Scenario) || 'ok';
  const { data: stations, error: stationsError } = useApi<Station[]>(
    () => LIVE_INDUSTRIAL ? industrial.stations() : Promise.resolve([]), [], LIVE_INDUSTRIAL ? 2000 : 0,
  );
  const stationId = LIVE_INDUSTRIAL
    ? stations?.find((station) => station.station_id === params.get('station'))?.station_id ?? stations?.[0]?.station_id
    : user?.stationId ?? 'A1·P06';
  const { data, error, reload } = useApi<OperatorView | null>(
    () => LIVE_INDUSTRIAL ? stationId ? operatorView(stationId) : Promise.resolve(null) : api.stationLive(stationId!, scenario),
    [stationId, scenario], 2000,
  );
  const live = data?.stationId === stationId ? data : null;
  const [reported, setReported] = useState(false);
  const [newVerdict, setNewVerdict] = useState<'' | 'OK' | 'NOK'>('');
  const [reason, setReason] = useState('');
  const [inspected, setInspected] = useState(false);
  const [actionMessage, setActionMessage] = useState('');

  if (!live && !error && !stationsError) return <Loading />;
  if (!live) return <div className="screen"><TopBar title="POSTE" /><div className="card" style={{ margin: 24 }}>Données industrielles indisponibles · {error ?? stationsError ?? 'aucun poste connu'}</div></div>;
  const actions: OperatorAction[] = LIVE_INDUSTRIAL
    ? live.issues.filter((issue) => ['SECURITE_EPI', 'COMPORTEMENT', 'POSTE'].includes(issue.category)).map((issue) => ({ key: issue.id, title: issue.label, subtitle: 'Observation synthétique ou industrielle', strong: issue.category !== 'POSTE' }))
    : operatorActions(live as StationLive);
  const envIssues = live.issues.filter((i) => i.category === 'SECURITE_EPI' || i.category === 'COMPORTEMENT' || i.category === 'POSTE');
  const ko = live.part?.verdict === 'KO';
  const multi = ko && envIssues.length > 0;
  if (LIVE_INDUSTRIAL && ko) actions.push({ key: 'piece', title: 'Pièce KO · verdict effectif', subtitle: 'Disposition physique non renseignée', strong: true });

  const report = async () => { if (!LIVE_INDUSTRIAL) { await api.reportProblem(stationId!); setReported(true); setTimeout(() => setReported(false), 4000); } };
  const correct = async (event: FormEvent) => {
    event.preventDefault();
    if (!live.industrialPart || !newVerdict || newVerdict === live.industrialPart.effective_verdict) return;
    try {
      await industrial.correct(live.industrialPart, newVerdict, reason, inspected);
      setActionMessage('Correction enregistrée · la disposition physique reste distincte.');
      setReason(''); setNewVerdict(''); reload();
    } catch (cause) { setActionMessage(String(cause)); }
  };

  return (
    <div className="screen" style={{ background: ko || envIssues.length ? 'var(--red-tint)' : 'var(--op-bg)' }}>
      <TopBar title={`POSTE ${live.stationId}`} sub={live.product ? `Presse injection · ${live.product}` : 'Produit non renseigné'} right={<><span className="sub hide-mobile">{live.shift ? LIVE_INDUSTRIAL ? `Shift ${live.shift.code} · ${live.shift.start} – ${live.shift.end}` : `Shift ${live.shift.code} · ${live.shift.start.slice(0, 2)} h – ${live.shift.end.slice(0, 2)} h` : 'Shift non renseigné'}</span><Clock iso={live.now} /></>} />

      {LIVE_INDUSTRIAL && <div className="row" style={{ padding: '8px 28px', gap: 12 }}><label>Poste <select className="btn" value={stationId} onChange={(e) => setParams({ station: e.target.value })}>{stations?.map((station) => <option key={station.station_id} value={station.station_id}>{station.station_id}</option>)}</select></label><span className="muted">{live.online ? 'Événement récent' : 'Aucun événement récent'}</span>{(error || stationsError) && <span style={{ color: 'var(--red-text)' }}>Connexion interrompue · dernières données reçues</span>}</div>}

      {envIssues.length > 0 && <ProblemBanner actions={actions} live={LIVE_INDUSTRIAL} />}

      <main className="row stack-mobile" style={{ flex: 1, alignItems: 'stretch', gap: 24, padding: '20px 28px 0' }}>
        {/* Colonne gauche : la pièce, ou l'image caméra si seul l'environnement est en défaut */}
        <section className="card-op col" style={{ width: 440, maxWidth: '100%', gap: 14 }}>
          {!ko && envIssues.length > 0 && (LIVE_INDUSTRIAL || live.frontSnapshotUrl)
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
                {live.counters.good != null && live.objective.shiftTarget != null && live.objective.shiftTarget > 0 && live.objective.expectedNow != null
                  ? <ProgressRing value={live.counters.good} target={live.objective.shiftTarget} expected={live.objective.expectedNow} />
                  : <div className="card" style={{ width: 220, height: 220, display: 'grid', placeItems: 'center' }}>Objectif indisponible</div>}
                <div className="col grow" style={{ gap: 16 }}>
                  <span className="label-caps" style={{ fontSize: 18 }}>Objectif du shift</span>
                  <div>
                    <div className="num" style={{ fontSize: 64 }}>{live.objective.shiftTarget == null || live.counters.good == null ? '—' : fmt(Math.max(0, live.objective.shiftTarget - live.counters.good))}</div>
                    <div className="muted" style={{ fontSize: 18, fontWeight: 600 }}>pièces à faire</div>
                  </div>
                  <div className="row">
                    <MiniStat value={live.counters.good == null || live.objective.expectedNow == null ? 'Rythme indisponible' : deltaText(live.counters.good - live.objective.expectedNow, true)} tone={live.counters.good != null && live.objective.expectedNow != null && live.counters.good >= live.objective.expectedNow ? 'green' : 'red'} />
                    <MiniStat value={`${live.counters.ko ?? '—'} pièces KO`} tone={ko ? 'red' : 'grey'} />
                  </div>
                  <span className="muted" style={{ fontSize: 14 }}>{live.objective.expectedNow == null ? 'Objectif du shift non renseigné' : `Trait noir : où vous devriez être maintenant (${Math.round(live.objective.expectedNow)})`}</span>
                </div>
              </div>
              <HourlyGauges timeline={shiftTimeline(live)} height={ko ? 48 : 56} />
            </div>
          )}

          <div className="grid-3">
            <StatusTile ok={live.checks.securite} icon={live.checks.securite ? ICONS.shield : ICONS.shieldAlert} okTitle="Sécurité OK" okSub="EPI portés" koTitle="Sécurité" koSub={envIssues.find((i) => i.category !== 'POSTE')?.label ?? ''} />
            <StatusTile ok={live.checks.poste} icon={ICONS.grid} okTitle="Poste rangé" okSub="Rien qui traîne" koTitle="Poste" koSub={envIssues.find((i) => i.category === 'POSTE')?.label ?? ''} />
            <StatusTile ok={live.checks.qualite ?? (LIVE_INDUSTRIAL ? null : true)} icon={ICONS.check} okTitle={ko ? 'Qualité' : 'Qualité OK'} okSub={`Taux KO ${live.checks.koRatePct == null ? 'indisponible' : live.checks.koRatePct.toLocaleString('fr-FR') + ' %'}`} koTitle="Qualité" koSub="Pièce à vérifier" />
          </div>

          <button onClick={report} disabled={LIVE_INDUSTRIAL} title={LIVE_INDUSTRIAL ? 'Endpoint transactionnel indisponible' : undefined} className="cond" style={{ height: 88, border: 'none', borderRadius: 26, background: reported ? 'var(--navy)' : 'var(--primary)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 18, fontWeight: 700, fontSize: 36, letterSpacing: '0.06em' }}>
            <Icon d={ICONS.flag} size={40} color="#fff" />
            {reported ? 'SUPERVISEUR PRÉVENU' : LIVE_INDUSTRIAL ? 'SIGNALER · INDISPONIBLE' : 'SIGNALER UN PROBLÈME'}
          </button>
          {LIVE_INDUSTRIAL && live.industrialPart && <form className="card-op row stack-mobile" onSubmit={correct} style={{ gap: 10, padding: 12 }}>
            <b>Correction après inspection humaine</b>
            <select aria-label="Nouveau verdict" className="btn" value={newVerdict} required onChange={(e) => setNewVerdict(e.target.value as 'OK' | 'NOK')}><option value="">Verdict</option><option value="OK">OK</option><option value="NOK">KO</option></select>
            <input aria-label="Motif de correction" className="btn grow" value={reason} minLength={3} maxLength={500} required placeholder="Motif" onChange={(e) => setReason(e.target.value)} />
            <label><input type="checkbox" checked={inspected} onChange={(e) => setInspected(e.target.checked)} /> Pièce inspectée</label>
            <button className="btn btn-primary" disabled={!newVerdict || newVerdict === live.industrialPart.effective_verdict || (['HOLD', 'ERROR'].includes(live.industrialPart.effective_verdict) && !inspected)}>Corriger</button>
            {actionMessage && <span>{actionMessage}</span>}
          </form>}
        </section>
      </main>

      <footer className="between muted" style={{ height: 40, alignItems: 'center', padding: '0 28px', fontSize: 13 }}>
        <span>{LIVE_INDUSTRIAL ? 'Image indisponible · aucune acquisition affichée' : 'Visage flouté · aucune vidéo enregistrée'}</span>
        <span>Caméra pièce {live.partCameraOnline == null ? 'état inconnu' : live.partCameraOnline ? 'en ligne' : 'hors ligne'} · modèle qualité {live.qualityModelVersion ?? 'indisponible'}</span>
      </footer>

      {USE_MOCK && !LIVE_INDUSTRIAL && <ScenarioSwitcher value={scenario} onChange={(s) => setParams({ scenario: s })} />}
    </div>
  );
}

function ProblemBanner({ actions, live = false }: { actions: OperatorAction[]; live?: boolean }) {
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
          <span style={{ fontSize: 18 }}>{live ? 'Épisode actif · résolution explicite dans le Core.' : 'Le voyant repassera au vert tout seul.'}</span>
        </>
      )}
    </div>
  );
}

function PartPanel({ live }: { live: OperatorView }) {
  const ko = live.part?.verdict === 'KO';
  const c = !live.part || live.part.verdict === 'A_VERIFIER' ? 'var(--amber)' : ko ? 'var(--red)' : 'var(--green)';
  return (
    <>
      <span className="label-caps" style={{ textAlign: 'center', fontSize: 18 }}>Pièce en cours · n° {live.part?.number ?? 'indisponible'}</span>
      <div style={{ height: ko ? 250 : 270, borderRadius: 18, overflow: 'hidden', border: `5px solid ${c}`, flexShrink: 0 }}>
        {live.part?.imageUrl
          ? <img src={live.part.imageUrl} alt={ko ? `Pièce non conforme : ${live.part.jointsDetected} joints détectés, zone en défaut entourée de rouge` : 'Pièce conforme : un seul joint détecté'} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
          : <div style={{ height: '100%', display: 'grid', placeItems: 'center', background: 'var(--surface-soft)', color: 'var(--muted)' }}>Image indisponible · nombre de joints inconnu</div>}
      </div>
      <div style={{ flex: 1, minHeight: 120, borderRadius: 20, background: c, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 22, padding: '0 20px' }}>
        <span className="num" style={{ fontSize: 96, lineHeight: 0.9 }}>{live.part ? ko ? 'KO' : live.part.verdict === 'OK' ? 'OK' : '—' : '—'}</span>
        <span style={{ fontSize: 18, fontWeight: 600, lineHeight: 1.3 }}>
          {live.live ? <>{live.part ? `Initial : ${live.predictedVerdict} · effectif : ${live.effectiveVerdict}` : 'Aucune pièce reçue'}<br />Score d’anomalie : {live.part?.score == null ? 'indisponible' : `${(live.part.score * 100).toFixed(1)} % de risque`}</> : ko ? <>{live.part?.jointsDetected === 0 ? 'Joint absent' : `${live.part?.jointsDetected} joints détectés`}<br />Posez la pièce dans le bac rebuts</> : <>1 joint bleu détecté<br />Le cycle est parti</>}
        </span>
      </div>
    </>
  );
}

function SnapshotPanel({ live, instruction }: { live: OperatorView; instruction: string }) {
  const t = new Date(live.now);
  return (
    <>
      <span className="label-caps" style={{ textAlign: 'center', fontSize: 18 }}>Ce que la caméra a vu · {String(t.getHours()).padStart(2, '0')}:{String(t.getMinutes()).padStart(2, '0')}</span>
      <div style={{ borderRadius: 18, overflow: 'hidden', border: '5px solid var(--red)', lineHeight: 0 }}>
        {live.frontSnapshotUrl ? <img src={live.frontSnapshotUrl} alt="Image de la caméra frontale, visage flouté, manquement encadré en rouge" style={{ width: '100%', display: 'block' }} /> : <div style={{ height: 250, display: 'grid', placeItems: 'center', background: 'var(--surface-soft)', color: 'var(--muted)' }}>Image frontale indisponible</div>}
      </div>
      <div className="col" style={{ flex: 1, justifyContent: 'center', gap: 6, borderRadius: 20, background: 'var(--red-bg)', border: '2px solid var(--red-light)', padding: '14px 20px' }}>
        <span className="cond" style={{ fontWeight: 700, fontSize: 30, color: 'var(--red-text)' }}>{instruction}</span>
        <span style={{ fontSize: 16, color: 'var(--red-dark)' }}>{live.live ? 'Observation reçue · aucune image de personne affichée.' : 'Le cadre rouge montre ce qui manque. Le voyant repasse au vert tout seul.'}</span>
      </div>
    </>
  );
}

function MultiCard({ live, actions }: { live: OperatorView; actions: OperatorAction[] }) {
  return (
    <div className="card-op row stack-mobile" style={{ flex: 1, border: '3px solid var(--red)', padding: '16px 20px', gap: 18, alignItems: 'stretch' }}>
      <div className="col" style={{ width: 340, maxWidth: '100%', flexShrink: 0, gap: 8 }}>
        <span className="label-caps">Ce que la caméra a vu</span>
        {live.frontSnapshotUrl && <img src={live.frontSnapshotUrl} alt="Image caméra frontale, visage flouté, manquements encadrés en rouge" style={{ width: '100%', borderRadius: 14 }} />}
        {!live.frontSnapshotUrl && <div className="muted" style={{ minHeight: 150, display: 'grid', placeItems: 'center' }}>Image indisponible</div>}
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

function ObjectiveStrip({ live }: { live: OperatorView }) {
  const { good } = live.counters, { shiftTarget, expectedNow } = live.objective;
  return (
    <div className="card-op row" style={{ padding: '12px 20px', gap: 18, borderRadius: 20 }}>
      <span className="label-caps" style={{ fontSize: 15 }}>Objectif</span>
      <span className="num" style={{ fontSize: 30, color: 'var(--green-text)' }}>{good ?? '—'} <span className="muted" style={{ fontSize: 18 }}>/ {shiftTarget == null ? '—' : fmt(shiftTarget)}</span></span>
      <div className="track grow" style={{ height: 12 }}><div className="fill" style={{ width: `${good != null && shiftTarget ? (good / shiftTarget) * 100 : 0}%`, background: 'var(--green)' }} /></div>
      <span style={{ fontSize: 15, fontWeight: 600 }}>{good == null || shiftTarget == null ? 'Objectif indisponible' : `${Math.max(0, shiftTarget - good)} à faire`}</span>
      <span style={{ fontSize: 15, fontWeight: 700, color: good != null && expectedNow != null && good >= expectedNow ? 'var(--green-text)' : 'var(--red-text)' }}>{good == null || expectedNow == null ? 'Rythme indisponible' : deltaText(good - expectedNow, true)}</span>
    </div>
  );
}

function MiniStat({ value, tone }: { value: string; tone: 'green' | 'red' | 'grey' }) {
  const bg = tone === 'green' ? 'var(--green-soft)' : tone === 'red' ? 'var(--red-soft)' : 'var(--op-bg)';
  const fg = tone === 'green' ? 'var(--green-text)' : tone === 'red' ? 'var(--red-text)' : 'var(--ink)';
  return <span className="cond" style={{ background: bg, color: fg, borderRadius: 16, padding: '10px 16px', fontWeight: 700, fontSize: 24 }}>{value}</span>;
}

function StatusTile({ ok, icon, okTitle, okSub, koTitle, koSub }: { ok: boolean | null; icon: string; okTitle: string; okSub: string; koTitle: string; koSub: string }) {
  return (
    <div className="row" style={{ background: '#fff', borderRadius: 20, padding: ok ? '14px 18px' : '11px 15px', border: ok ? 'none' : `3px solid ${ok === null ? 'var(--amber)' : 'var(--red)'}`, gap: 14 }}>
      <span style={{ width: 48, height: 48, borderRadius: 24, background: ok === null ? 'var(--amber)' : ok ? 'var(--green)' : 'var(--red)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Icon d={icon} size={26} color="#fff" stroke={2.4} /></span>
      <div>
        <div className="cond" style={{ fontWeight: 700, fontSize: 22, color: ok === null ? 'var(--amber-text)' : ok ? 'var(--ink)' : 'var(--red-text)' }}>{ok === null ? koTitle || okTitle : ok ? okTitle : koTitle}</div>
        <div style={{ fontSize: 14, color: ok ? 'var(--muted)' : 'var(--red-dark)' }}>{ok === null ? 'État inconnu' : ok ? okSub : koSub}</div>
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
