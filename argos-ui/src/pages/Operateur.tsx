import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, USE_MOCK, type ReportCategory } from '../api/client';
import type { Scenario } from '../api/mock';
import type { Alert, StationLive, WorkstationStartup } from '../api/types';
import { useAuth } from '../auth';
import { HourlyGauges, ProgressRing } from '../components/charts';
import { operatorActions, type OperatorAction } from '../components/priority';
import { Clock, deltaText, fmt, Icon, ICONS, Loading, TopBar } from '../components/ui';
import { useApi } from '../hooks/useApi';

/**
 * Écran du poste. Un seul écran qui s'adapte à l'état reçu :
 * tout va bien · pièce KO · EPI ou poste en défaut · plusieurs problèmes en même temps.
 * En démo : ?scenario=ok|ko|epi|multi
 *
 * Prise de poste : tant que l'espace de travail n'est pas validé (`live.startup`), la
 * colonne de gauche montre la photo du poste à la place de la pièce. Une pièce KO en
 * attente (`part.awaitingConfirmation`) affiche le bouton CONFIRMER.
 *
 * Le même écran sert au team leader qui CONSULTE un poste depuis son PC (`consultStationId`) :
 * il voit exactement ce que voit l'opérateur, sans le bouton Signaler, avec en plus
 * les alertes du poste qu'il peut prendre en charge.
 */
export default function Operateur({ consultStationId }: { consultStationId?: string }) {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const scenario = (params.get('scenario') as Scenario) || 'ok';
  const consult = !!consultStationId;
  const stationId = consultStationId ?? user?.stationId ?? 'C3·P06';
  const { data: rawLive, reload } = useApi(() => api.stationLive(stationId, scenario), [stationId, scenario], 1000);
  const [requalifiedPart, setRequalifiedPart] = useState<number | null>(null);
  const cellId = user?.cellId ?? 'C3';
  const { data: cellAlerts, setData: setCellAlerts } = useApi(() => (consult ? api.alerts(cellId) : Promise.resolve([] as Alert[])), [consult, cellId], 5000);
  const [reported, setReported] = useState(false);
  const [choosing, setChoosing] = useState(false); // « Signaler » : choix de la catégorie

  if (!rawLive) return <Loading />;
  // Pièce KO revérifiée par l'opérateur et requalifiée OK : on l'affiche OK tout de suite.
  const live: StationLive = rawLive.part.verdict === 'KO' && requalifiedPart === rawLive.part.number
    ? { ...rawLive, part: { ...rawLive.part, verdict: 'OK', requalified: true }, checks: { ...rawLive.checks, qualite: true } }
    : rawLive;
  const requalify = async () => { await api.requalifyPart(stationId, live.part.number); setRequalifiedPart(live.part.number); };
  const actions = operatorActions(live);
  const envIssues = live.issues.filter((i) => i.category === 'SECURITE_EPI' || i.category === 'COMPORTEMENT' || i.category === 'POSTE');
  const ko = live.part.verdict === 'KO';
  const multi = ko && envIssues.length > 0;
  const hour = new Date(live.now).getHours();
  const startup = live.startup && live.startup.phase !== 'RUNNING' ? live.startup : null;
  const confirm = async () => { await api.confirmPart(stationId); reload(); };
  const release = async () => { await api.releasePart(stationId); reload(); };
  const restartDemo = async () => { await api.restartScenario(stationId); reload(); };

  const report = async (category: ReportCategory) => {
    setChoosing(false);
    await api.reportProblem(stationId, category);
    setReported(true);
    setTimeout(() => setReported(false), 4000);
  };
  const stationAlerts = (cellAlerts ?? []).filter((a) => a.stationId === stationId);
  const acknowledge = (id: string) => api.acknowledgeAlert(id).then(() => setCellAlerts((cellAlerts ?? []).map((a) => (a.id === id ? { ...a, acknowledgedBy: user?.name ?? 'Team leader', acknowledgedAt: new Date().toISOString() } : a))));
  const shiftChip = <span className="chip hide-mobile">Shift {live.shift.code} · {live.shift.start.slice(0, 2)} h – {live.shift.end.slice(0, 2)} h</span>;

  return (
    <div className="screen" style={{ background: ko || envIssues.length ? 'var(--red-tint)' : 'var(--op-bg)' }}>
      <TopBar
        // Démo : un clic sur le logo HOVIS démarre ou relance la simulation (mode live).
        onLogoClick={!USE_MOCK && !consult ? restartDemo : undefined}
        title={`POSTE ${live.stationId}`}
        sub={`Presse injection · ${live.product}`}
        right={consult
          ? <><Link to="/team-leader" className="chip" style={{ color: '#fff', fontWeight: 600 }}>← Ma cellule</Link><Clock iso={live.now} /></>
          : <>{shiftChip}<Clock iso={live.now} /></>}
      />

      {consult && <ConsultBar stationId={live.stationId} alerts={stationAlerts} onAcknowledge={acknowledge} />}

      {envIssues.length > 0 && <ProblemBanner actions={actions} />}

      <main className="row stack-mobile" style={{ flex: 1, alignItems: 'stretch', gap: 24, padding: '20px 28px 0' }}>
        {/* Colonne gauche : la pièce, ou l'image caméra si seul l'environnement est en défaut */}
        <section className="card-op col" style={{ width: 440, maxWidth: '100%', gap: 14 }}>
          {startup
            ? <StartupPanel startup={startup} />
            : !ko && envIssues.length > 0 && live.frontSnapshotUrl
              ? <SnapshotPanel live={live} instruction={envIssues[0].instruction} />
              : <PartPanel live={live} onConfirm={consult ? undefined : confirm} onRelease={consult ? undefined : release} onRequalify={consult ? undefined : requalify} />}
        </section>

        <section className="col grow" style={{ gap: 18 }}>
          {startup ? (
            <StartupCard startup={startup} />
          ) : multi ? (
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
                    <MiniStat value={`${live.counters.ko} pièces NOK`} tone={ko ? 'red' : 'grey'} />
                  </div>
                  <span className="muted" style={{ fontSize: 14 }}>Trait noir (anneau et barre) : où vous devriez être maintenant ({live.objective.expectedNow})</span>
                </div>
              </div>
              <HourlyGauges hours={live.hourly} perHour={live.objective.perHour} currentHour={hour} expected={live.objective.expectedNow} height={ko ? 28 : 34} />
            </div>
          )}

          <div className="grid-3">
            <StatusTile ok={live.checks.securite} icon={live.checks.securite ? ICONS.shield : ICONS.shieldAlert} okTitle="Sécurité OK" okSub="EPI portés" koTitle="Sécurité" koSub={envIssues.find((i) => i.category !== 'POSTE')?.label ?? ''} />
            <StatusTile ok={live.checks.poste} icon={ICONS.grid} okTitle="Poste rangé" okSub="Rien qui traîne" koTitle="Poste" koSub={envIssues.find((i) => i.category === 'POSTE')?.label ?? ''} />
            <StatusTile ok icon={ICONS.check} okTitle={ko ? 'Qualité' : 'Qualité OK'} okSub={`Taux NOK ${live.checks.koRatePct.toLocaleString('fr-FR')} %`} koTitle="" koSub="" />
          </div>

          {!consult && (
            <button onClick={() => setChoosing(true)} className="cond btn-report" data-done={reported} style={{ height: 88, border: 'none', borderRadius: 26, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 18, fontWeight: 700, fontSize: 36, letterSpacing: '0.06em' }}>
              <Icon d={ICONS.flag} size={40} color="currentColor" stroke={2.4} />
              {reported ? 'TEAM LEADER PRÉVENU' : 'SIGNALER UN PROBLÈME'}
            </button>
          )}
        </section>
      </main>
      {choosing && <ReportChoice onChoose={report} onCancel={() => setChoosing(false)} />}

      <footer className="between muted" style={{ height: 40, alignItems: 'center', padding: '0 28px', fontSize: 13 }}>
        <span>Visage flouté · aucune vidéo enregistrée{live.qualityModelVersion === 'simulé' && <button onClick={() => api.simulateNokPart()} style={{ marginLeft: 16, border: '1px solid var(--line)', background: '#fff', borderRadius: 8, padding: '2px 8px', fontSize: 12, color: 'var(--muted)' }}>Démo · simuler une pièce NOK</button>}</span>
        <span>Caméra pièce {live.partCameraOnline ? 'en ligne' : 'hors ligne'} · modèle qualité {live.qualityModelVersion}</span>
      </footer>

      {USE_MOCK && <ScenarioSwitcher value={scenario} onChange={(s) => setParams({ scenario: s })} />}
    </div>
  );
}

/** Bandeau du team leader qui consulte un poste : lecture seule + alertes du poste à acquitter. */
function ConsultBar({ stationId, alerts, onAcknowledge }: { stationId: string; alerts: Alert[]; onAcknowledge: (id: string) => void }) {
  return (
    <div className="row" style={{ background: 'var(--navy-2)', color: '#fff', padding: '10px 28px', gap: 14, flexWrap: 'wrap' }}>
      <Icon d={ICONS.monitor} size={24} color="#fff" />
      <span style={{ fontWeight: 600 }}>Vous consultez l’écran du poste {stationId}</span>
      <span style={{ color: 'var(--on-navy-muted)', fontSize: 14 }}>lecture seule · même vue que l’opérateur</span>
      <span style={{ flex: 1 }} />
      {alerts.map((a) => (
        <span key={a.id} className="row" style={{ gap: 8, background: 'rgba(255,255,255,.08)', borderRadius: 12, padding: '4px 4px 4px 12px' }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{a.title}</span>
          {a.acknowledgedBy
            ? <span className="pill pill-green">Prise en charge{a.acknowledgedAt ? ` · ${new Date(a.acknowledgedAt).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}` : ''}</span>
            : <button className="btn-report" onClick={() => onAcknowledge(a.id)} style={{ border: 'none', borderRadius: 10, padding: '6px 12px', fontWeight: 700, fontSize: 14, boxShadow: 'none' }}>Prendre en charge</button>}
        </span>
      ))}
      <Link to={`/team-leader/poste/${encodeURIComponent(stationId)}/historique`} className="chip" style={{ color: '#fff', fontWeight: 600 }}>Historique du shift</Link>
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

function PartPanel({ live, onConfirm, onRelease, onRequalify }: { live: StationLive; onConfirm?: () => void; onRelease?: () => void; onRequalify?: () => Promise<void> }) {
  const ko = live.part.verdict === 'KO';
  const c = ko ? 'var(--red)' : 'var(--green)';
  const waiting = ko && live.part.awaitingConfirmation; // demo scenario: CONFIRMER / LAISSER PASSER
  const [checking, setChecking] = useState(false);
  return (
    <>
      <span className="label-caps" style={{ textAlign: 'center', fontSize: 18 }}>Pièce en cours · n° {live.part.number}</span>
      <div style={{ height: ko ? 250 : 270, borderRadius: 18, overflow: 'hidden', border: `5px solid ${c}`, flexShrink: 0 }}>
        <img src={live.part.imageUrl} alt={ko ? `Pièce non conforme : ${live.part.jointsDetected} joints détectés, zone en défaut entourée de rouge` : 'Pièce conforme : un seul joint détecté'} style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#0b1220', display: 'block' }} />
      </div>
      <div style={{ flex: 1, minHeight: 120, borderRadius: 20, background: c, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 22, padding: '0 20px' }}>
        <span className="num" style={{ fontSize: 120, lineHeight: 0.9 }}>{ko ? 'NOK' : 'OK'}</span>
      </div>
      {waiting && onConfirm && onRelease && (
        <div className="row" style={{ gap: 10 }}>
          <button onClick={onConfirm} className="cond" style={{ flex: 1, height: 52, border: 'none', borderRadius: 14, background: 'var(--navy)', color: '#fff', fontWeight: 700, fontSize: 20, letterSpacing: '0.05em', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
            <Icon d={ICONS.check} size={22} color="#fff" stroke={2.6} />
            CONFIRMER
          </button>
          <button onClick={onRelease} className="cond" style={{ flex: 1, height: 52, borderRadius: 14, background: '#fff', color: 'var(--navy)', border: '2px solid var(--navy)', fontWeight: 700, fontSize: 16, letterSpacing: '0.03em', lineHeight: 1.1 }}>
            LAISSER PASSER<br /><span style={{ fontSize: 12, fontWeight: 600 }}>erreur modèle</span>
          </button>
        </div>
      )}
      {ko && !waiting && onRequalify && (checking ? (
        <div className="col" style={{ gap: 8, borderRadius: 16, border: '2px solid var(--line-strong)', background: '#fff', padding: '12px 14px' }}>
          <span style={{ fontSize: 17, fontWeight: 600 }}>Regardez la pièce : y a-t-il un seul joint, bien placé ?</span>
          <div className="row" style={{ gap: 10 }}>
            <button onClick={async () => { await onRequalify(); setChecking(false); }} style={{ flex: 1, height: 48, border: 'none', borderRadius: 12, background: 'var(--green)', color: '#fff', fontWeight: 700, fontSize: 17 }}>Oui, la pièce est OK</button>
            <button onClick={() => setChecking(false)} style={{ flex: 1, height: 48, borderRadius: 12, border: '2px solid var(--line-strong)', background: '#fff', color: 'var(--ink)', fontWeight: 700, fontSize: 17 }}>Non, elle est bien NOK</button>
          </div>
        </div>
      ) : (
        <button onClick={() => setChecking(true)} style={{ height: 52, borderRadius: 14, border: '2px solid var(--ink)', background: '#fff', color: 'var(--ink)', fontWeight: 700, fontSize: 18, flexShrink: 0 }}>Revérifier la pièce</button>
      ))}
    </>
  );
}

const REPORT_CHOICES: { category: ReportCategory; label: string; sub: string }[] = [
  { category: 'QUALITY_MODEL', label: 'Modèle Quality', sub: 'Verdict de la pièce faux' },
  { category: 'WORKSTATION_MODEL', label: 'Modèle Workspace', sub: 'Verdict du poste faux' },
  { category: 'EPI_MODEL', label: 'Modèle EPI', sub: 'Alerte sécurité fausse' },
  { category: 'MACHINE', label: 'Problème machine', sub: 'Panne, bruit, fuite…' },
];

/** « Signaler un problème » : l'opérateur choisit la catégorie, le team leader reçoit l'alerte. */
function ReportChoice({ onChoose, onCancel }: { onChoose: (c: ReportCategory) => void; onCancel: () => void }) {
  return (
    <div role="dialog" aria-modal="true" aria-label="Quel problème signaler ?" onClick={onCancel}
      style={{ position: 'fixed', inset: 0, zIndex: 40, background: 'rgba(11,31,63,.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div className="card-op col" onClick={(e) => e.stopPropagation()} style={{ gap: 18, padding: '26px 30px', width: 760, maxWidth: '100%' }}>
        <span className="cond" style={{ fontSize: 34, fontWeight: 700 }}>Quel problème ?</span>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          {REPORT_CHOICES.map((c) => (
            <button key={c.category} onClick={() => onChoose(c.category)} className="cond btn-report"
              style={{ minHeight: 120, border: 'none', borderRadius: 22, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 6, padding: 12 }}>
              <span style={{ fontWeight: 700, fontSize: 30 }}>{c.label}</span>
              <span style={{ fontWeight: 600, fontSize: 17 }}>{c.sub}</span>
            </button>
          ))}
        </div>
        <button onClick={onCancel} style={{ height: 60, borderRadius: 16, border: '2px solid var(--ink)', background: '#fff', color: 'var(--ink)', fontWeight: 700, fontSize: 22 }}>Annuler</button>
      </div>
    </div>
  );
}

/** Prise de poste : la photo du poste à la place de la pièce, avec son verdict. */
function StartupPanel({ startup }: { startup: WorkstationStartup }) {
  if (startup.phase === 'IDLE' || startup.phase === 'OFF') {
    return (
      <>
        <span className="label-caps" style={{ textAlign: 'center', fontSize: 18 }}>{startup.phase === 'OFF' ? 'Poste arrêté' : 'Vérification du poste'}</span>
        <div style={{ flex: 1, minHeight: 300, borderRadius: 18, border: '5px solid var(--op-bg)', background: 'var(--op-bg)' }} />
      </>
    );
  }
  const ok = startup.verdict === 'OK';
  const c = ok ? 'var(--green)' : 'var(--red)';
  return (
    <>
      <span className="label-caps" style={{ textAlign: 'center', fontSize: 18 }}>
        Vérification du poste · photo {startup.step} / {startup.step}
      </span>
      <div style={{ borderRadius: 18, overflow: 'hidden', border: `5px solid ${c}`, lineHeight: 0 }}>
        <img src={startup.imageUrl} alt={ok ? 'Photo du poste : conforme à la référence' : 'Photo du poste : écart encadré'} style={{ width: '100%', display: 'block' }} />
      </div>
      <div style={{ flex: 1, minHeight: 120, borderRadius: 20, background: c, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span className="num" style={{ fontSize: 120, lineHeight: 0.9 }}>{ok ? 'OK' : 'NOK'}</span>
      </div>
    </>
  );
}

/** Colonne de droite pendant la prise de poste : ce qui se passe et pourquoi. */
function StartupCard({ startup }: { startup: WorkstationStartup }) {
  const validated = startup.phase === 'VALIDATED';
  if (startup.phase === 'IDLE' || startup.phase === 'OFF') {
    return (
      <div className="card-op col" style={{ gap: 14, padding: '22px 30px', flex: 1 }}>
        <span className="label-caps" style={{ fontSize: 18 }}>Prise de poste</span>
        <div className="num" style={{ fontSize: 44, lineHeight: 1.05 }}>{startup.phase === 'OFF' ? "Pas d'activité sur ce poste" : 'En attente de la prise de poste'}</div>
      </div>
    );
  }
  return (
    <div className="card-op col" style={{ gap: 14, padding: '22px 30px', flex: 1 }}>
      <span className="label-caps" style={{ fontSize: 18 }}>Prise de poste</span>
      <div className="num" style={{ fontSize: 44, lineHeight: 1.05, color: validated ? 'var(--green-text)' : 'var(--ink)' }}>
        {validated ? "Poste validé : l'activité commence" : "Vérification de l'espace de travail"}
      </div>
      <span className="muted" style={{ fontSize: 18 }}>
        Avant toute activité, la photo du poste est comparée à sa référence ({startup.section}) :
        rien dans les zones interdites, chaque élément à sa place. Cette vérification n'est faite qu'une fois.
      </span>
      {/* n / n : la progression ne dit pas combien de photos il reste */}
      <span className="muted" style={{ fontSize: 15, fontWeight: 600 }}>photo {startup.step} / {startup.step}</span>
    </div>
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
  const opts: [Scenario, string][] = [['ok', 'Conforme'], ['ko', 'Pièce NOK'], ['epi', 'EPI manquant'], ['multi', 'Plusieurs problèmes']];
  return (
    <div style={{ position: 'fixed', left: '50%', transform: 'translateX(-50%)', bottom: 4, background: 'var(--navy)', color: '#fff', borderRadius: 12, padding: 4, display: 'flex', gap: 4, boxShadow: '0 8px 24px rgba(0,0,0,.3)', fontSize: 12 }}>
      <span style={{ alignSelf: 'center', padding: '0 6px', color: 'var(--on-navy-muted)' }}>Démo</span>
      {opts.map(([k, l]) => (
        <button key={k} onClick={() => onChange(k)} style={{ border: 'none', borderRadius: 9, padding: '5px 9px', fontWeight: 700, background: value === k ? 'var(--primary)' : 'transparent', color: '#fff' }}>{l}</button>
      ))}
    </div>
  );
}
