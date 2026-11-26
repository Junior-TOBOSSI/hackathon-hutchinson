import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { AlertCategory, StationStatus } from '../api/types';
import { Donut, HourlyBars, StackedHistogram, type Category } from '../components/charts';
import { Clock, CountBadge, DeltaPill, deltaText, fmt, Icon, ICONS, Kpi, Loading, TopBar } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { LIVE_INDUSTRIAL } from '../api/industrial';
import { industrial } from '../api/industrial';
import { workshopDisplay, workshopView, type DisplayAlert, type DisplayCell, type DisplayLine, type WorkshopDisplay, type WorkshopLive } from '../api/industrial-view';

/**
 * Cockpit du superviseur (manager) : PC, tablette ou téléphone.
 * Aucune image de personne : les alertes sont du texte (poste, heure, shift, description).
 */
type Tab = 'overview' | 'prod' | 'alerts' | 'equip';

export const CATEGORIES: (Category & { key: AlertCategory })[] = [
  { key: 'SECURITE_EPI', name: 'Sécurité et EPI', color: 'var(--cat-securite)' },
  { key: 'POSTE', name: 'Poste', color: 'var(--cat-poste)' },
  { key: 'QUALITE', name: 'Qualité', color: 'var(--cat-qualite)' },
  { key: 'RYTHME', name: 'Rythme', color: 'var(--cat-rythme)' },
  { key: 'EQUIPEMENT', name: 'Équipement', color: 'var(--cat-equipement)' },
];

const lineGood = (l: DisplayLine) => l.cells.reduce((s, c) => s + c.good, 0);
const lineExpected = (l: DisplayLine) => l.cells.every((c) => c.expectedNow != null) ? l.cells.reduce((s, c) => s + c.expectedNow!, 0) : null;
const lineShiftTarget = (l: DisplayLine) => l.cells.every((c) => c.target != null) ? l.cells.reduce((s, c) => s + c.target!, 0) : null;

export default function Superviseur() {
  const { data: mockOv } = useApi(() => LIVE_INDUSTRIAL ? Promise.resolve(null) : api.overview(), [], LIVE_INDUSTRIAL ? 0 : 15000);
  const { data: mockAlerts, setData: setAlerts } = useApi(() => LIVE_INDUSTRIAL ? Promise.resolve(null) : api.alerts(), [], LIVE_INDUSTRIAL ? 0 : 5000);
  const { data: liveData, error, reload } = useApi<WorkshopLive | null>(() => LIVE_INDUSTRIAL ? workshopView() : Promise.resolve(null), [], LIVE_INDUSTRIAL ? 4000 : 0);
  const display = liveData ? workshopDisplay(liveData) : null;
  const ov: WorkshopDisplay | null = LIVE_INDUSTRIAL ? display?.overview ?? null : mockOv;
  const alerts: DisplayAlert[] | null = LIVE_INDUSTRIAL ? display?.alerts ?? null : mockAlerts;
  const [tab, setTab] = useState<Tab>('overview');
  const [lineId, setLineId] = useState('A');
  const [cellId, setCellId] = useState<string | null>(null);

  if (!ov || !alerts) return error ? <div className="screen"><TopBar title="Atelier injection" /><div className="card" style={{ margin: 24 }}>Données industrielles indisponibles · {error}</div></div> : <Loading />;
  const camsDown = LIVE_INDUSTRIAL ? liveData?.stations.flatMap((station) => station.equipment).filter((item) => item.equipment_type === 'camera' && item.status === 'down').length ?? 0 : ov.lines.reduce((s, l) => s + (l.cameras.front[1]! - l.cameras.front[0]!) + (l.cameras.part[1]! - l.cameras.part[0]!), 0);

  const tabs: { key: Tab; label: string; icon: string; badge?: number; hot?: boolean }[] = [
    { key: 'overview', label: 'Vue d’ensemble', icon: ICONS.overview },
    { key: 'prod', label: 'Production', icon: ICONS.bars },
    { key: 'alerts', label: 'Alertes', icon: ICONS.warn, badge: alerts.length, hot: alerts.some((a) => a.priority) },
    { key: 'equip', label: 'Équipements', icon: ICONS.camera, badge: camsDown },
  ];
  const removeAlert = (id: string) => LIVE_INDUSTRIAL ? reload() : setAlerts((mockAlerts ?? []).filter((a) => a.id !== id));

  return (
    <div className="screen">
      <TopBar title="Atelier injection" sub={LIVE_INDUSTRIAL ? `${liveData?.stations.length ?? 0} postes · ligne non configurée` : `${ov.lines.length} lignes · Shift ${ov.currentShift!.code} en cours`} right={<Clock iso={new Date().toISOString()} />} />
      <nav className="tabs" role="tablist">
        {tabs.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className="tab" onClick={() => setTab(t.key)}>
            <Icon d={t.icon} size={22} />{t.label}<CountBadge n={t.badge ?? 0} hot={t.hot} />
          </button>
        ))}
        <span style={{ flex: 1 }} className="hide-mobile" />
        <span className="muted hide-mobile" style={{ alignSelf: 'center', fontSize: 14, fontWeight: 600 }}>{ov.date} · {ov.currentShift ? `shift ${ov.currentShift.code} en cours` : 'shifts par poste'}</span>
      </nav>

      <main className="col page-sup" style={{ padding: '20px 24px', gap: 16, flex: 1 }}>
        {error && <div className="card pill-red">Connexion interrompue · dernières données reçues : {error}</div>}
        {tab === 'overview' && <Overview ov={ov} alerts={alerts} openLine={(id) => { setLineId(id); setCellId(null); setTab('prod'); }} openAlerts={() => setTab('alerts')} />}
        {tab === 'prod' && <Production ov={ov} lineId={lineId} setLineId={(id) => { setLineId(id); setCellId(null); }} cellId={cellId} setCellId={setCellId} />}
        {tab === 'alerts' && <Alerts alerts={alerts} onDone={removeAlert} />}
        {tab === 'equip' && <Equipment ov={ov} alerts={alerts} />}
      </main>
    </div>
  );
}

/* ---------------- Vue d'ensemble : objectif de la journée ---------------- */
function Overview({ ov, alerts, openLine, openAlerts }: { ov: WorkshopDisplay; alerts: DisplayAlert[]; openLine: (id: string) => void; openAlerts: () => void }) {
  const finished = ov.lines.reduce((s, l) => s + l.finishedShifts.reduce((a, f) => a + f.good, 0), 0);
  const finishedTarget = ov.lines.reduce((s, l) => s + l.finishedShifts.reduce((a, f) => a + f.target, 0), 0);
  const dayGood = finished + ov.lines.reduce((s, l) => s + lineGood(l), 0);
  const dayExpected = ov.lines.every((line) => lineExpected(line) != null) ? finishedTarget + ov.lines.reduce((s, l) => s + lineExpected(l)!, 0) : null;
  const koRate = ov.industrial ? ov.industrial.global.nok_rate == null ? null : ov.industrial.global.nok_rate * 100 : (ov.koDay / (dayGood + ov.koDay)) * 100;
  const cams = ov.industrial ? null : ov.lines.reduce((a, l) => [a[0] + l.cameras.front[0]! + l.cameras.part[0]!, a[1] + l.cameras.front[1]! + l.cameras.part[1]!], [0, 0]);
  const totals = CATEGORIES.map((c) => ({ name: c.name, color: c.color, value: ov.lines.reduce((s, l) => s + (ov.problemsByLine[l.id]?.[c.key] ?? 0), 0) }));

  return (
    <>
      <div className="grid-5">
        <Kpi label={ov.industrial ? 'Pièces bonnes · 8 h' : 'Pièces bonnes · journée'} value={fmt(dayGood)} sub={ov.dayTarget == null || dayExpected == null ? 'Objectif global indisponible' : `sur ${fmt(ov.dayTarget)} · ${Math.round((dayGood / ov.dayTarget) * 100)} % · ${deltaText(dayGood - dayExpected).toLowerCase()}`} />
        <Kpi label={ov.industrial ? 'Pièces KO · 8 h' : 'Pièces KO · journée'} value={fmt(ov.koDay)} sub={ov.industrial ? 'Verdicts effectifs du Core' : Object.entries(ov.koByShift).map(([k, v]) => `shift ${k} ${v}`).join(' · ')} />
        <Kpi label={ov.industrial ? 'Taux de KO · 8 h' : 'Taux de KO · journée'} value={koRate == null ? '—' : `${koRate.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} %`} sub={ov.industrial ? 'Objectif non renseigné' : 'objectif < 2 %'} />
        <button onClick={openAlerts} style={{ all: 'unset', cursor: 'pointer', display: 'grid' }}><Kpi label="Alertes ouvertes" value={alerts.length} sub={`${alerts.filter((a) => a.priority).length} prioritaires`} valueStyle={{ color: 'var(--red)' }} /></button>
        <Kpi label="Caméras actives" value={cams ? `${cams[0]} / ${cams[1]}` : ov.industrial?.stations.some((station) => station.equipment.some((item) => item.equipment_type === 'camera')) ? `${ov.industrial.stations.flatMap((station) => station.equipment).filter((item) => item.equipment_type === 'camera' && item.status === 'ok').length} / ?` : '—'} sub={cams ? `${cams[1] - cams[0]} hors ligne` : 'Parc installé non renseigné'} />
      </div>

      <div className="grid-3">
        {ov.lines.map((l) => <LineCard key={l.id} line={l} live={!!ov.industrial} onOpen={() => openLine(l.id)} />)}
      </div>

      <div className="row stack-mobile" style={{ gap: 14, alignItems: 'stretch' }}>
        <div className="card grow col">
          <div className="between"><h2 className="h2">Problèmes détectés par ligne · {ov.currentShift ? `shift ${ov.currentShift.code}` : 'épisodes actifs'}</h2><span className="muted" style={{ fontSize: 13 }}>Touchez une colonne pour voir les alertes</span></div>
          <StackedHistogram categories={CATEGORIES} onPick={openAlerts} groups={ov.lines.map((l) => ({ key: l.id, name: l.name, values: ov.problemsByLine[l.id] ?? {} }))} />
        </div>
        <div className="card col" style={{ width: 420, maxWidth: '100%' }}>
          <h2 className="h2">Répartition par catégorie</h2>
          <Donut items={totals} centerLabel="problèmes" />
        </div>
      </div>
    </>
  );
}

function LineCard({ line, live, onOpen }: { line: DisplayLine; live: boolean; onOpen: () => void }) {
  const shiftTarget = lineShiftTarget(line);
  const dayTarget = live || shiftTarget == null ? null : shiftTarget * 3;
  const finished = line.finishedShifts.reduce((s, f) => s + f.good, 0);
  const good = lineGood(line);
  const dayGood = finished + good;
  const expected = lineExpected(line);
  const d = live || expected == null ? null : dayGood - (line.finishedShifts.reduce((s, f) => s + f.target, 0) + expected);
  const segs = live ? [{ label: 'Shifts non renseignés', pct: 0, cur: false }] : (['A', 'B', 'C'] as const).map((code) => {
    const f = line.finishedShifts.find((x) => x.code === code);
    if (f) return { label: `${code} · ${Math.round((f.good / f.target) * 100)} %`, pct: (f.good / f.target) * 100, cur: false };
    if (code === 'B' && shiftTarget) return { label: `B · en cours ${Math.round((good / shiftTarget) * 100)} %`, pct: (good / shiftTarget) * 100, cur: true };
    return { label: `${code} · à venir`, pct: 0, cur: false };
  });
  return (
    <button onClick={onOpen} className="card col" style={{ border: 'none', textAlign: 'left', gap: 12, color: 'var(--ink)' }}>
      <div className="between" style={{ alignItems: 'center' }}><span className="cond" style={{ fontWeight: 700, fontSize: 26 }}>{line.name}</span>{d == null ? <span className="muted">Objectif inconnu</span> : <DeltaPill d={d} />}</div>
      <div className="row" style={{ alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <span className="num" style={{ fontSize: 40, whiteSpace: 'nowrap' }}>{dayTarget ? `${Math.round((dayGood / dayTarget) * 100)} %` : `${dayGood} pièces`}</span>
        <span className="muted" style={{ fontSize: 15 }}>{live ? 'bonnes · 8 dernières heures' : 'de l’objectif de la journée atteint'}</span>
      </div>
      <div className="grid-3" style={{ gap: 6, gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
        {segs.map((s) => (
          <div key={s.label} className="col" style={{ gap: 5 }}>
            <div className="track"><div className="fill" style={{ width: `${s.pct}%`, background: s.cur ? 'var(--green-light)' : 'var(--green)' }} /></div>
            <span style={{ fontSize: 12, fontWeight: s.cur ? 700 : 600 }} className={s.cur ? '' : 'muted'}>{s.label}</span>
          </div>
        ))}
      </div>
      <span className="muted" style={{ fontSize: 13 }}>{live ? 'Hiérarchie de lignes non configurée dans le Core' : `Shifts A, B, C · ${fmt(dayGood)} pièces bonnes sur ${fmt(dayTarget!)} pour la journée`}</span>
      <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--primary)' }}>Voir la production de la ligne →</span>
    </button>
  );
}

/* ---------------- Production : ligne > cellules > postes ---------------- */
const STATUS: Record<StationStatus, [string, string]> = {
  OK: ['Tout va bien', 'pill-green'], SECURITE: ['Sécurité', 'pill-solid-red'], QUALITE: ['Qualité', 'pill-solid-red'],
  RYTHME: ['Rythme', 'pill-amber'], CAMERA: ['Caméra hors ligne', 'pill-amber'], OBJET: ['Objet étranger', 'pill-amber'],
};

function Production({ ov, lineId, setLineId, cellId, setCellId }: { ov: WorkshopDisplay; lineId: string; setLineId: (id: string) => void; cellId: string | null; setCellId: (id: string) => void }) {
  const line = ov.lines.find((l) => l.id === lineId) ?? ov.lines[0];
  const cell: DisplayCell | undefined = line.cells.find((c) => c.id === cellId) ?? line.cells[0];
  const hour = new Date().getHours();
  return (
    <>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {ov.lines.map((l) => (
          <button key={l.id} className="btn" onClick={() => setLineId(l.id)} style={l.id === line.id ? { background: 'var(--navy)', color: '#fff' } : { background: '#fff', color: 'var(--ink)', border: '2px solid var(--line)' }}>{l.name}</button>
        ))}
      </div>
      <div className="card col" style={{ gap: 8 }}>
        <div className="between"><h2 className="h2">{line.name} · cellules</h2><span className="muted hide-mobile" style={{ fontSize: 13 }}>Pièces bonnes / objectif du shift · trait noir = attendu maintenant · touchez une cellule</span></div>
        {line.cells.map((c) => {
          const sel = c.id === cell?.id;
          return (
            <button key={c.id} onClick={() => setCellId(c.id)} className="row" style={{ width: '100%', padding: 10, borderRadius: 12, border: 'none', background: sel ? 'var(--primary-soft)' : 'transparent', color: 'var(--ink)', gap: 14 }}>
              <span className="cond" style={{ width: 54, fontWeight: 700, fontSize: 22, textAlign: 'left' }}>{c.id}</span>
              <div className="track grow" style={{ height: 22, borderRadius: 6, overflow: 'visible' }}>
                <div className="fill" style={{ width: `${c.target ? (c.good / c.target) * 100 : 0}%`, background: sel ? 'var(--green)' : 'var(--green-light)' }} />
                {c.target && c.expectedNow != null && <div style={{ position: 'absolute', left: `${(c.expectedNow / c.target) * 100}%`, top: -4, width: 3, height: 30, borderRadius: 2, background: 'var(--navy)' }} />}
              </div>
              <span className="hide-mobile" style={{ width: 110, textAlign: 'right', fontWeight: 600 }}>{fmt(c.good)} / {c.target == null ? '—' : fmt(c.target)}</span>
              <span style={{ width: 110, textAlign: 'right', fontWeight: 700, color: c.expectedNow != null && c.good >= c.expectedNow ? 'var(--green-text)' : 'var(--red-text)' }}>{c.expectedNow == null ? 'Objectif inconnu' : deltaText(c.good - c.expectedNow, true)}</span>
              <span className="muted" style={{ width: 70, textAlign: 'right', fontSize: 14 }}>{c.ko} KO</span>
            </button>
          );
        })}
      </div>
      <div className="card col" style={{ gap: 10 }}>
        <div className="between"><h2 className="h2">Cellule {cell?.id ?? 'non configurée'} · postes</h2><span className="muted" style={{ fontSize: 13 }}>Touchez un poste pour son détail</span></div>
        <div className="grid-6">
          {cell?.stations.map((s) => {
            const hot = s.status === 'SECURITE' || s.status === 'QUALITE';
            return (
              <Link key={s.id} to={`/superviseur/poste/${encodeURIComponent(s.id)}`} className="col" style={{ gap: 6, padding: 14, borderRadius: 16, background: hot ? 'var(--red-bg)' : 'var(--surface-soft)', border: `2px solid ${hot ? 'var(--red)' : 'var(--track)'}` }}>
                <span className="cond" style={{ fontWeight: 700, fontSize: 22 }}>{ov.industrial ? s.id : s.id.split('·')[1]}</span>
                <span style={{ fontWeight: 700, fontSize: 15, color: s.deltaVsExpected != null && s.deltaVsExpected < 0 ? 'var(--red-text)' : 'var(--green-text)' }}>{s.deltaVsExpected == null ? 'Objectif inconnu' : deltaText(s.deltaVsExpected, true)}</span>
                {ov.industrial && <span className="muted" style={{ fontSize: 13 }}>Objectif shift {ov.industrial.stations.find((station) => station.station_id === s.id)?.current_shift?.kpi.target_parts ?? '—'}</span>}
                <span className={`pill ${s.status ? STATUS[s.status][1] : 'pill-amber'}`} style={{ alignSelf: 'flex-start' }}>{s.status ? STATUS[s.status][0] : s.online === false ? 'Aucun événement récent' : 'État inconnu'}</span>
              </Link>
            );
          })}
        </div>
      </div>
      <div className="card col">
        <div className="between"><h2 className="h2">Cellule {cell?.id ?? 'non configurée'} · pièces bonnes par heure</h2><span className="muted" style={{ fontSize: 13 }}>{cell?.target == null ? 'Objectif horaire indisponible' : `Trait noir : ${Math.round(cell.target / 8)} / h pour tenir l’objectif`}</span></div>
        <HourlyBars hours={cell?.hourly ?? []} perHour={cell?.target == null ? null : Math.round(cell.target / 8)} currentHour={hour} />
        {!cell?.hourly && <span className="muted">Historique horaire indisponible ou limité par la pagination.</span>}
      </div>
    </>
  );
}

/* ---------------- Alertes : toutes les lignes, texte seul ---------------- */
function Alerts({ alerts, onDone }: { alerts: DisplayAlert[]; onDone: (id: string) => void }) {
  const [cat, setCat] = useState<AlertCategory | 'ALL'>('ALL');
  const list = useMemo(() => [...alerts].filter((a) => cat === 'ALL' || a.category === cat).sort((a, b) => Number(b.priority) - Number(a.priority)), [alerts, cat]);
  const chip = (k: AlertCategory | 'ALL', label: string) => (
    <button key={k} onClick={() => setCat(k)} className="pill" style={{ padding: '8px 14px', borderRadius: 18, fontSize: 14, border: cat === k ? 'none' : '1px solid var(--line)', background: cat === k ? 'var(--navy)' : '#fff', color: cat === k ? '#fff' : 'var(--ink)' }}>{label}</button>
  );
  return (
    <>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        {chip('ALL', `Toutes · ${alerts.length}`)}
        {CATEGORIES.map((c) => chip(c.key, c.name))}
        <span style={{ flex: 1 }} />
        <span className="muted" style={{ fontSize: 14 }}>Une alerte = un épisode par poste, jamais en double</span>
      </div>
      <div className="grid-2" style={{ alignContent: 'start' }}>
        {list.map((a) => <AlertCard key={a.id} a={a} onDone={() => onDone(a.id)} />)}
      </div>
      {!list.length && <div className="card pill-green" style={{ fontWeight: 600 }}>Aucune alerte en cours.</div>}
    </>
  );
}

function AlertCard({ a, onDone }: { a: DisplayAlert; onDone: () => void }) {
  const cat = CATEGORIES.find((c) => c.key === a.category)!;
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const act = async (action: 'acknowledge' | 'validate' | 'reject' | 'resolve') => {
    setBusy(true); setError('');
    try { await industrial.alertAction(a.id, action); onDone(); }
    catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };
  return (
    <div className="card col" style={{ gap: 8, border: `2px solid ${a.priority ? 'var(--red)' : 'var(--line)'}` }}>
      <div className="row" style={{ gap: 10 }}>
        <span className="cond" style={{ fontWeight: 700, fontSize: 26 }}>{a.stationId}</span>
        <span className={`pill ${a.category === 'SECURITE_EPI' ? 'pill-red' : 'pill-blue'}`}>{cat.name}</span>
        <span style={{ flex: 1 }} />
        <span className="muted" style={{ fontSize: 13 }}>{a.reportedByOperator ? 'signalé par l’opérateur' : ''}</span>
      </div>
      <span style={{ fontSize: 16, fontWeight: 700 }}>{a.title}</span>
      <span className="muted" style={{ fontSize: 14 }}>{a.detail}</span>
      <span style={{ fontSize: 14, fontWeight: 600 }}>Shift {a.shift} · {a.when}{a.core ? ` · statut ${a.core.status}` : ''}</span>
      {a.action === 'NONE' && <span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>Pour information : aucune validation demandée</span>}
      {error && <span style={{ color: 'var(--red-text)' }}>{error}</span>}
      <div className="row" style={{ gap: 8 }}>
        {a.core && a.core.status === 'open' && <button disabled={busy} className="btn btn-soft grow" onClick={() => act('acknowledge')}>Acquitter</button>}
        {a.core && ['open', 'acknowledged'].includes(a.core.status) && <><button disabled={busy} className="btn btn-primary grow" onClick={() => act('validate')}>Valider</button><button disabled={busy} className="btn btn-ghost grow" onClick={() => act('reject')}>Rejeter</button></>}
        {a.core && ['open', 'acknowledged', 'validated'].includes(a.core.status) && <button disabled={busy} className="btn btn-dark grow" onClick={() => act('resolve')}>Résoudre</button>}
        {!a.core && a.action === 'VALIDATE' && (
          <>
            <button className="btn btn-primary grow" onClick={() => api.decideAlert(a.id, 'VALIDER').then(onDone)}>Valider</button>
            <button className="btn btn-ghost grow" onClick={() => api.decideAlert(a.id, 'REJETER').then(onDone)}>Rejeter</button>
          </>
        )}
        {!a.core && a.action === 'MAINTENANCE' && <button className="btn btn-dark" style={{ flex: 2 }} onClick={() => api.callMaintenance(a.id)}>Appeler la maintenance</button>}
        <Link to={`/superviseur/poste/${encodeURIComponent(a.stationId)}`} className="btn btn-soft grow">Voir le poste</Link>
      </div>
    </div>
  );
}

/* ---------------- Équipements ---------------- */
function Equipment({ ov, alerts }: { ov: WorkshopDisplay; alerts: DisplayAlert[] }) {
  const all = ov.industrial ? null : ov.lines.reduce((a, l) => [a[0] + l.cameras.front[0]! + l.cameras.part[0]!, a[1] + l.cameras.front[1]! + l.cameras.part[1]!], [0, 0]);
  const down = alerts.filter((a) => a.category === 'EQUIPEMENT');
  const st = (v: [number | null, number | null]) => ({ fontWeight: v[0] != null && v[1] != null && v[0] < v[1] ? 700 : 600, color: v[0] == null || v[1] == null ? 'var(--muted)' : v[0] < v[1] ? 'var(--red-text)' : 'var(--green-text)' });
  return (
    <>
      <div className="row stack-mobile" style={{ gap: 16, alignItems: 'stretch' }}>
        <div className="card col grow">
          <div className="between"><h2 className="h2">Caméras actives</h2><span className="num" style={{ fontSize: 34 }}>{all ? all[0] : ov.industrial?.stations.some((station) => station.equipment.some((item) => item.equipment_type === 'camera')) ? ov.industrial.stations.flatMap((station) => station.equipment).filter((item) => item.equipment_type === 'camera' && item.status === 'ok').length : '—'} <span className="muted" style={{ fontSize: 18 }}>/ {all ? all[1] : 'nombre inconnu'} installées</span></span></div>
          {ov.lines.map((l) => {
            const a = l.cameras.front[0] == null || l.cameras.part[0] == null ? l.cameras.part[0] ?? null : l.cameras.front[0] + l.cameras.part[0];
            const t = l.cameras.front[1] == null || l.cameras.part[1] == null ? null : l.cameras.front[1] + l.cameras.part[1];
            return (
              <div key={l.id} className="row">
                <span style={{ width: 70, fontWeight: 600 }}>{l.name}</span>
                <div className="track grow" style={{ height: 18, background: 'var(--red-light)' }}><div className="fill" style={{ width: `${a != null && t ? (a / t) * 100 : 0}%`, background: 'var(--green)' }} /></div>
                <span style={{ width: 60, textAlign: 'right', fontWeight: 700 }}>{a ?? '—'} / {t ?? '—'}</span>
              </div>
            );
          })}
          <span className="muted" style={{ fontSize: 13 }}>{ov.industrial ? 'Seuls les équipements déclarés par le Core sont connus.' : 'Vert = en ligne · rose = installée mais hors ligne'}</span>
        </div>
        <div className="card col" style={{ width: 460, maxWidth: '100%', gap: 10 }}>
          <h2 className="h2">Hors ligne</h2>
          {down.map((a) => (
            <div key={a.id} className="row" style={{ padding: '12px 14px', borderRadius: 14, background: 'var(--red-bg)' }}>
              <span style={{ width: 10, height: 10, borderRadius: 5, background: 'var(--red)' }} />
              <span className="grow" style={{ fontWeight: 600, color: 'var(--red-dark)' }}>{a.stationId} · {a.title}</span>
              <span className="muted" style={{ fontSize: 13 }}>{a.when}</span>
            </div>
          ))}
          {ov.industrial && !down.length && <span className="muted">Aucune alerte équipement active ; état des équipements non déclarés inconnu.</span>}
        </div>
      </div>
      <div className="card col" style={{ overflowX: 'auto' }}>
        <h2 className="h2">État par ligne</h2>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 16, minWidth: 560 }}>
          <thead><tr className="muted" style={{ fontSize: 13, textAlign: 'left', letterSpacing: '0.06em' }}>
            <th style={{ padding: '6px 0' }}>LIGNE</th><th>CAMÉRAS FRONTALES</th><th>CAMÉRAS PIÈCE</th><th>MINI-PC</th><th>MODÈLES EN SERVICE</th>
          </tr></thead>
          <tbody>
            {ov.lines.map((l) => (
              <tr key={l.id} style={{ borderTop: '1px solid var(--line-soft)' }}>
                <td style={{ padding: '12px 0', fontWeight: 700 }}>{l.name}</td>
                <td style={st(l.cameras.front)}>{l.cameras.front[0] ?? '—'} / {l.cameras.front[1] ?? '—'}</td>
                <td style={st(l.cameras.part)}>{l.cameras.part[0] ?? '—'} / {l.cameras.part[1] ?? '—'}</td>
                <td style={st(l.cameras.front)}>{ov.industrial ? 'Non renseigné' : `${l.cameras.front[0]} / ${l.cameras.front[1]} joignables`}</td>
                <td className="muted">{ov.industrial ? 'Versions non renseignées' : 'qualité v1.3 · EPI v2.0'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
