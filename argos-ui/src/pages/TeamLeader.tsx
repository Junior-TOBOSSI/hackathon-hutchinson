import { useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, USE_MOCK } from '../api/client';
import type { Alert, AlertCategory, CellOverview, StationStatus, StationSummary } from '../api/types';
import { useAuth } from '../auth';
import { CumulativeChart, type Category } from '../components/charts';
import { Clock, CountBadge, deltaText, fmt, Icon, ICONS, Kpi, Loading, TopBar } from '../components/ui';
import { useApi } from '../hooks/useApi';

/**
 * Écran du team leader (PC) : les postes de SA cellule et leurs alertes.
 * L'interface ne montre rien au-dessus de la cellule (ni les autres cellules, ni l'UAP).
 * Depuis un poste ou une alerte, il ouvre l'écran du poste (consultation) ou son historique.
 */
type Tab = 'stations' | 'alerts';

export const CATEGORIES: (Category & { key: AlertCategory })[] = [
  { key: 'SECURITE_EPI', name: 'Sécurité et EPI', color: 'var(--cat-securite)' },
  { key: 'POSTE', name: 'Poste', color: 'var(--cat-poste)' },
  { key: 'QUALITE', name: 'Qualité', color: 'var(--cat-qualite)' },
  { key: 'RYTHME', name: 'Rythme', color: 'var(--cat-rythme)' },
  { key: 'EQUIPEMENT', name: 'Équipement', color: 'var(--cat-equipement)' },
];

const STATUS: Record<StationStatus, [string, string]> = {
  OK: ['Conforme', 'pill-green'], SECURITE: ['Sécurité', 'pill-solid-red'], QUALITE: ['Qualité', 'pill-solid-red'],
  RYTHME: ['Rythme', 'pill-amber'], CAMERA: ['Caméra hors ligne', 'pill-amber'], OBJET: ['Objet étranger', 'pill-amber'],
  ARRET: ["Pas d'activité", 'pill-grey'],
};

/** Adresse de l'écran d'un poste. En démo, il s'ouvre sur le scénario qui correspond à l'état du poste. */
export function stationScreenUrl(stationId: string, status?: StationStatus) {
  const url = `/team-leader/poste/${encodeURIComponent(stationId)}`;
  if (!USE_MOCK || !status) return url;
  const scenario = status === 'SECURITE' ? 'epi' : status === 'QUALITE' ? 'ko' : 'ok';
  return `${url}?scenario=${scenario}`;
}
export const stationHistoryUrl = (stationId: string) => `/team-leader/poste/${encodeURIComponent(stationId)}/historique`;
const shortId = (stationId: string) => stationId.split('·')[1] ?? stationId;

export default function TeamLeader() {
  const { user } = useAuth();
  const cellId = user?.cellId ?? 'C3';
  const { data: cell } = useApi(() => api.cellOverview(cellId), [cellId], 15000);
  const { data: alerts, setData: setAlerts } = useApi(() => api.alerts(cellId), [cellId], 5000);
  const [tab, setTab] = useState<Tab>('stations');

  if (!cell || !alerts) return <Loading />;
  const watched = cell.stations.filter((s) => s.status !== 'OK').length;
  const tabs: { key: Tab; label: string; icon: string; badge?: number; hot?: boolean }[] = [
    { key: 'stations', label: 'Postes', icon: ICONS.overview, badge: watched },
    { key: 'alerts', label: 'Alertes', icon: ICONS.warn, badge: alerts.length, hot: alerts.some((a) => a.priority) },
  ];
  const removeAlert = (id: string) => setAlerts(alerts.filter((a) => a.id !== id));
  const acknowledge = (id: string) => api.acknowledgeAlert(id).then(() => setAlerts(alerts.map((a) => (a.id === id ? { ...a, acknowledgedBy: user?.name ?? 'Team leader', acknowledgedAt: new Date().toISOString() } : a))));

  return (
    <div className="screen">
      <TopBar title={cell.cell.name} sub={`${cell.uap.name} · ${cell.stations.length} postes · shift ${cell.currentShift.code} en cours`} right={<Clock iso={new Date().toISOString()} />} />
      <nav className="tabs" role="tablist">
        {tabs.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className="tab" onClick={() => setTab(t.key)}>
            <Icon d={t.icon} size={22} />{t.label}<CountBadge n={t.badge ?? 0} hot={t.hot} />
          </button>
        ))}
        <span style={{ flex: 1 }} className="hide-mobile" />
        <span className="muted hide-mobile" style={{ alignSelf: 'center', fontSize: 14, fontWeight: 600 }}>{cell.date} · shift {cell.currentShift.code} · {cell.currentShift.start} – {cell.currentShift.end}</span>
      </nav>

      <main className="col page-sup" style={{ padding: '20px 24px', gap: 16, flex: 1 }}>
        {tab === 'stations' && <Stations cell={cell} alerts={alerts} openAlerts={() => setTab('alerts')} />}
        {tab === 'alerts' && <Alerts cell={cell} alerts={alerts} onDone={removeAlert} onAcknowledge={acknowledge} />}
      </main>
    </div>
  );
}

/* ---------------- Postes de la cellule ---------------- */
function Stations({ cell, alerts, openAlerts }: { cell: CellOverview; alerts: Alert[]; openAlerts: () => void }) {
  const good = cell.stations.reduce((s, st) => s + st.good, 0);
  const target = cell.stations.reduce((s, st) => s + st.target, 0);
  const expected = cell.stations.reduce((s, st) => s + st.expectedNow, 0);
  const ko = cell.stations.reduce((s, st) => s + st.ko, 0);
  const koRate = (ko / (good + ko)) * 100;
  const watched = cell.stations.filter((s) => s.status !== 'OK').length;

  return (
    <>
      <div className="grid-5">
        <Kpi label="Pièces bonnes · shift" value={fmt(good)} sub={`sur ${fmt(target)} · ${Math.round((good / target) * 100)} % de l’objectif`} />
        <Kpi label="Rythme de la cellule" value={deltaText(good - expected, true)} valueStyle={{ fontSize: 30, color: good >= expected ? 'var(--green-text)' : 'var(--red-text)' }} sub={`${fmt(expected)} pièces attendues à cette heure`} />
        <Kpi label="Pièces NOK · shift" value={fmt(ko)} sub={`taux de NOK ${koRate.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} % · objectif < 2 %`} />
        <button onClick={openAlerts} style={{ all: 'unset', cursor: 'pointer', display: 'grid' }}>
          <Kpi label="Alertes ouvertes" value={alerts.length} sub={`${alerts.filter((a) => a.priority).length} prioritaires · voir les alertes`} valueStyle={{ color: 'var(--red)' }} />
        </button>
        <Kpi label="Postes à surveiller" value={`${watched} / ${cell.stations.length}`} sub="sécurité, qualité, rythme ou équipement" />
      </div>

      <div className="card col" style={{ gap: 8 }}>
        <div className="between">
          <h2 className="h2">Postes</h2>
          <span className="muted hide-mobile" style={{ fontSize: 13 }}>Cliquez sur un poste pour voir son détail</span>
        </div>
        <StationTable stations={cell.stations} alerts={alerts} />
      </div>

      <div className="card col">
        <div className="between">
          <h2 className="h2">Production de la cellule</h2>
          <span className="muted" style={{ fontSize: 13 }}>Pièces bonnes cumulées depuis {cell.currentShift.start} · l’écart avec l’objectif = avance ou retard</span>
        </div>
        <CumulativeChart hourly={cell.hourly} target={target} expectedNow={expected} shiftStart={Number(cell.currentShift.start.slice(0, 2))} />
      </div>
    </>
  );
}

/** Pastille d'état : couleur + libellé (jamais la couleur seule). */
const DOT: Record<StationStatus, string> = {
  OK: 'var(--green)', SECURITE: 'var(--red)', QUALITE: 'var(--red)', RYTHME: 'var(--amber)', CAMERA: 'var(--amber)', OBJET: 'var(--amber)', ARRET: '#9aa3ad',
};

/** Fond très léger de la carte, selon l'état du poste (la pastille et le libellé restent l'info principale). */
const TINT: Record<StationStatus, string> = {
  OK: '#d5eedf', SECURITE: '#f8d3da', QUALITE: '#f8d3da', RYTHME: '#fbe3c0', CAMERA: '#fbe3c0', OBJET: '#fbe3c0', ARRET: '#eceef1',
};
/** Réglage système « réduire les animations » : la carte en alerte reste alors fixe. */
const REDUCED_MOTION = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
/** Contour de la carte : la même couleur que le fond, un ton plus soutenu. */
const EDGE: Record<StationStatus, string> = {
  OK: '#9fd6b6', SECURITE: '#eb99a7', QUALITE: '#eb99a7', RYTHME: '#efbf78', CAMERA: '#efbf78', OBJET: '#efbf78', ARRET: '#cfd4da',
};

/**
 * Postes en cartes : une carte par poste, dans l'ordre physique de la cellule, avec 3 infos
 * seulement (état, rythme, pièces NOK). Un clic ouvre le détail du poste sous la grille.
 * Filtres : état du poste et recherche par nom (« P06 », « 6 »…).
 */
function StationTable({ stations, alerts }: { stations: StationSummary[]; alerts: Alert[] }) {
  const nav = useNavigate();
  const [status, setStatus] = useState<StationStatus | 'ALL'>('ALL');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string | null>(null);

  const q = query.trim().toUpperCase().replace(/^P0?/, '');
  const filtered = stations.filter((s) =>
    (status === 'ALL' || s.status === status) && (!q || shortId(s.id).replace(/^P0?/, '').startsWith(q)));
  const present = (Object.keys(STATUS) as StationStatus[]).filter((k) => stations.some((s) => s.status === k));
  const detail = stations.find((s) => s.id === selected);

  return (
    <div className="col" style={{ gap: 12 }}>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        {/* Taper un poste OU le choisir dans la liste (datalist : liste déroulante native) ;
            choisir un poste ouvre aussi son détail. */}
        <input
          aria-label="Rechercher ou choisir un poste"
          placeholder="Poste (taper ou choisir)"
          list="cell-stations"
          value={query}
          onChange={(e) => {
            const v = e.target.value;
            setQuery(v);
            const hit = stations.find((s) => shortId(s.id) === v.trim().toUpperCase());
            if (hit) setSelected(hit.id);
          }}
          style={{ height: 38, width: 220, borderRadius: 10, border: '2px solid var(--line-strong)', padding: '0 12px', fontFamily: 'var(--font)', fontSize: 15 }}
        />
        <datalist id="cell-stations">
          {stations.map((s) => <option key={s.id} value={shortId(s.id)}>{STATUS[s.status][0]}</option>)}
        </datalist>
        {query && <button className="icon-btn" onClick={() => { setQuery(''); setSelected(null); }} aria-label="Effacer le poste" title="Effacer">✕</button>}
        <FilterChip active={status === 'ALL'} onClick={() => setStatus('ALL')}>Tous · {stations.length}</FilterChip>
        {present.map((k) => (
          <FilterChip key={k} active={status === k} onClick={() => setStatus(k)}>
            <span style={{ width: 9, height: 9, borderRadius: 5, background: DOT[k] }} />
            {STATUS[k][0]} · {stations.filter((s) => s.status === k).length}
          </FilterChip>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: 12 }}>
        {filtered.map((s) => {
          const delta = s.good - s.expectedNow;
          const isSel = s.id === selected;
          const safe = s.status !== 'SECURITE';
          const off = s.status === 'ARRET'; // pas d'activité : ni sécurité, ni rythme, ni pièces
          return (
            <button
              key={s.id}
              onClick={() => setSelected(isSel ? null : s.id)}
              aria-expanded={isSel}
              aria-label={off ? `Poste ${shortId(s.id)} : pas d'activité. Voir le détail` : `Poste ${shortId(s.id)} : sécurité ${safe ? 'OK' : 'NOK'}, ${deltaText(delta, true)}, ${s.good} pièces OK, ${s.ko} pièces NOK. Voir le détail`}
              className="col"
              style={{ all: 'unset', cursor: 'pointer', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', gap: 7, padding: '14px 16px', borderRadius: 16, background: TINT[s.status],
                border: isSel ? '2px solid var(--navy)' : `2px solid ${EDGE[s.status]}`,
                animation: (s.status === 'SECURITE' || s.status === 'QUALITE') && !REDUCED_MOTION ? 'station-alert 0.8s ease-in-out infinite' : undefined }}
            >
              <span className="cond" style={{ fontWeight: 700, fontSize: 26, lineHeight: 1 }}>{shortId(s.id)}</span>
              {off ? (
                <span className="col" style={{ flex: 1, justifyContent: 'center', alignItems: 'center', gap: 4, minHeight: 96, color: '#4b5563' }}>
                  <b style={{ fontSize: 19 }}>Pas d'activité</b>
                  <span style={{ fontSize: 14 }}>Poste à l'arrêt</span>
                </span>
              ) : (
                <>
                  <CardLine label="Sécurité" value={safe ? 'OK' : 'NOK'} tone={safe ? 'ok' : 'bad'} />
                  <CardLine label="Rythme" value={deltaText(delta, true)} tone={delta < 0 ? 'bad' : 'ok'} />
                  <CardLine label="Pièces OK" value={fmt(s.good)} />
                  <CardLine label="Pièces NOK" value={fmt(s.ko)} />
                </>
              )}
            </button>
          );
        })}
      </div>
      {!filtered.length && <div className="muted" style={{ padding: '18px 10px' }}>Aucun poste ne correspond au filtre.</div>}

      {detail && <StationDetailPanel s={detail} alerts={alerts.filter((a) => a.stationId === detail.id)} onClose={() => setSelected(null)} onScreen={() => nav(stationScreenUrl(detail.id, detail.status))} />}
    </div>
  );
}

/** Une ligne de carte : libellé à gauche, valeur à droite (verte si OK, rouge sinon). */
function CardLine({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'bad' }) {
  return (
    <span className="between" style={{ alignItems: 'baseline', fontSize: 15 }}>
      <span style={{ color: 'var(--muted)' }}>{label}</span>
      <b style={{ fontSize: 16, color: tone === 'ok' ? 'var(--green-text)' : tone === 'bad' ? 'var(--red-text)' : 'var(--ink)' }}>{value}</b>
    </span>
  );
}

/** Détail d'un poste, ouvert d'un clic sur sa carte. */
function StationDetailPanel({ s, alerts, onClose, onScreen }: { s: StationSummary; alerts: Alert[]; onClose: () => void; onScreen: () => void }) {
  const delta = s.good - s.expectedNow;
  return (
    <div className="col" style={{ gap: 14, border: '2px solid var(--navy)', borderRadius: 16, padding: '16px 20px', background: '#fff' }}>
      <div className="between" style={{ alignItems: 'center' }}>
        <span className="row" style={{ gap: 14 }}>
          <span className="cond" style={{ fontWeight: 700, fontSize: 26 }}>Poste {shortId(s.id)}</span>
          <span className="row" style={{ gap: 8, fontWeight: 600 }}><span style={{ width: 10, height: 10, borderRadius: 5, background: DOT[s.status] }} />{STATUS[s.status][0]}</span>
          <span className="muted" style={{ fontSize: 14 }}>{s.product}</span>
        </span>
        <button onClick={onClose} className="icon-btn" aria-label="Fermer le détail" title="Fermer">✕</button>
      </div>
      {s.status === 'ARRET' ? (
        <span style={{ fontSize: 17, fontWeight: 600, color: '#4b5563' }}>Pas d'activité : ce poste est à l'arrêt, aucune pièce produite.</span>
      ) : (<>
      <div className="col" style={{ gap: 6 }}>
        <div className="between"><span className="muted" style={{ fontSize: 14 }}>Avancement du shift · attendu maintenant : {fmt(s.expectedNow)}</span><span style={{ fontWeight: 700 }}>{fmt(s.good)} / {fmt(s.target)}</span></div>
        <div className="track" style={{ height: 12, overflow: 'visible' }}>
          <div className="fill" style={{ width: `${(s.good / s.target) * 100}%`, background: delta >= 0 ? 'var(--green)' : 'var(--amber)' }} />
        </div>
      </div>
      <div className="row" style={{ gap: 28, flexWrap: 'wrap' }}>
        <span><span className="muted" style={{ fontSize: 14 }}>Rythme </span><b style={{ color: delta < 0 ? 'var(--red-text)' : 'var(--green-text)' }}>{deltaText(delta, true)}</b></span>
        <span><span className="muted" style={{ fontSize: 14 }}>Pièces NOK </span><b>{s.ko}</b> <span className="muted" style={{ fontSize: 14 }}>({((s.ko / Math.max(1, s.good + s.ko)) * 100).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} %)</span></span>
      </div>
      </>)}
      <div className="col" style={{ gap: 4 }}>
        <span className="muted" style={{ fontSize: 14 }}>Alertes en cours</span>
        {alerts.length ? alerts.map((a) => <span key={a.id} style={{ fontWeight: 600, color: 'var(--red-text)' }}>{a.title} <span className="muted" style={{ fontWeight: 400 }}>· {a.when}</span></span>) : <span className="muted">Aucune</span>}
      </div>
      <div className="row" style={{ gap: 10 }}>
        <button className="btn btn-dark" onClick={onScreen} style={{ padding: '10px 18px', borderRadius: 12 }}>Voir l’écran du poste</button>
        <Link to={stationHistoryUrl(s.id)} className="btn btn-ghost" style={{ padding: '10px 18px', borderRadius: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center' }}>Historique du shift</Link>
      </div>
    </div>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick} aria-pressed={active} className="row" style={{ gap: 6, height: 38, padding: '0 14px', borderRadius: 19, fontSize: 14, fontWeight: 600, border: active ? 'none' : '1px solid var(--line)', background: active ? 'var(--navy)' : '#fff', color: active ? '#fff' : 'var(--ink)' }}>
      {children}
    </button>
  );
}

/* ---------------- Alertes de la cellule : texte seul ---------------- */
const ackTime = (iso?: string) => (iso ? ` · ${new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}` : '');

function Alerts({ cell, alerts, onDone, onAcknowledge }: { cell: CellOverview; alerts: Alert[]; onDone: (id: string) => void; onAcknowledge: (id: string) => void }) {
  const [cat, setCat] = useState<AlertCategory | 'ALL'>('ALL');
  const list = useMemo(() => [...alerts].filter((a) => cat === 'ALL' || a.category === cat).sort((a, b) => Number(b.priority) - Number(a.priority)), [alerts, cat]);
  const chip = (k: AlertCategory | 'ALL', label: string) => (
    <button key={k} onClick={() => setCat(k)} className="pill" style={{ padding: '8px 14px', borderRadius: 18, fontSize: 14, border: cat === k ? 'none' : '1px solid var(--line)', background: cat === k ? 'var(--navy)' : '#fff', color: cat === k ? '#fff' : 'var(--ink)' }}>{label}</button>
  );
  const statusOf = (stationId: string) => cell.stations.find((s) => s.id === stationId)?.status;
  return (
    <>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        {chip('ALL', `Toutes · ${alerts.length}`)}
        {CATEGORIES.map((c) => chip(c.key, c.name))}
        <span style={{ flex: 1 }} />
        <span className="muted" style={{ fontSize: 14 }}>Une alerte = un épisode par poste, jamais en double</span>
      </div>
      <div className="grid-2" style={{ alignContent: 'start' }}>
        {list.map((a) => <AlertCard key={a.id} a={a} status={statusOf(a.stationId)} onDone={() => onDone(a.id)} onAcknowledge={() => onAcknowledge(a.id)} />)}
      </div>
      {!list.length && <div className="card pill-green" style={{ fontWeight: 600 }}>Aucune alerte en cours.</div>}
    </>
  );
}

export function AlertCard({ a, status, onDone, onAcknowledge }: { a: Alert; status?: StationStatus; onDone: () => void; onAcknowledge: () => void }) {
  const cat = CATEGORIES.find((c) => c.key === a.category)!;
  return (
    <div className="card col" style={{ gap: 8, border: `2px solid ${a.priority && !a.acknowledgedBy ? 'var(--red)' : 'var(--line)'}` }}>
      <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
        <span className="cond" style={{ fontWeight: 700, fontSize: 26 }}>{a.stationId}</span>
        <span className={`pill ${a.category === 'SECURITE_EPI' ? 'pill-red' : 'pill-blue'}`}>{cat.name}</span>
        {a.acknowledgedBy && <span className="pill pill-green">Prise en charge · {a.acknowledgedBy}{ackTime(a.acknowledgedAt)}</span>}
        <span style={{ flex: 1 }} />
        <span className="muted" style={{ fontSize: 13 }}>{a.reportedByOperator ? 'signalé par l’opérateur' : ''}</span>
      </div>
      <span style={{ fontSize: 16, fontWeight: 700 }}>{a.title}</span>
      <span className="muted" style={{ fontSize: 14 }}>{a.detail}</span>
      <span style={{ fontSize: 14, fontWeight: 600 }}>Shift {a.shift} · {a.when}</span>
      {a.action === 'NONE' && <span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>Pour information : aucune validation demandée</span>}
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {!a.acknowledgedBy && <button className="btn btn-primary grow" onClick={onAcknowledge}>Prendre en charge</button>}
        {a.action === 'VALIDATE' && (
          <>
            <button className="btn btn-dark grow" onClick={() => api.decideAlert(a.id, 'VALIDER').then(onDone)}>Valider</button>
            <button className="btn btn-ghost grow" onClick={() => api.decideAlert(a.id, 'REJETER').then(onDone)}>Rejeter</button>
          </>
        )}
        {a.action === 'MAINTENANCE' && <button className="btn btn-dark grow" onClick={() => api.callMaintenance(a.id)}>Appeler la maintenance</button>}
      </div>
      <div className="row" style={{ gap: 8 }}>
        <Link to={stationScreenUrl(a.stationId, status)} className="btn btn-soft grow" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>Voir l’écran du poste</Link>
        <Link to={stationHistoryUrl(a.stationId)} className="btn btn-soft grow" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>Historique</Link>
      </div>
    </div>
  );
}
