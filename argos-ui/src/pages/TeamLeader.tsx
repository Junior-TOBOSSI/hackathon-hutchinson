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
  OK: ['Tout va bien', 'pill-green'], SECURITE: ['Sécurité', 'pill-solid-red'], QUALITE: ['Qualité', 'pill-solid-red'],
  RYTHME: ['Rythme', 'pill-amber'], CAMERA: ['Caméra hors ligne', 'pill-amber'], OBJET: ['Objet étranger', 'pill-amber'],
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
  const acknowledge = (id: string) => api.acknowledgeAlert(id).then(() => setAlerts(alerts.map((a) => (a.id === id ? { ...a, acknowledgedBy: user?.name ?? 'Team leader' } : a))));

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
        <Kpi label="Pièces KO · shift" value={fmt(ko)} sub={`taux de KO ${koRate.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} % · objectif < 2 %`} />
        <button onClick={openAlerts} style={{ all: 'unset', cursor: 'pointer', display: 'grid' }}>
          <Kpi label="Alertes ouvertes" value={alerts.length} sub={`${alerts.filter((a) => a.priority).length} prioritaires · voir les alertes`} valueStyle={{ color: 'var(--red)' }} />
        </button>
        <Kpi label="Postes à surveiller" value={`${watched} / ${cell.stations.length}`} sub="sécurité, qualité, rythme ou équipement" />
      </div>

      <div className="card col" style={{ gap: 8 }}>
        <div className="between">
          <h2 className="h2">Postes de la {cell.cell.name.toLowerCase()}</h2>
          <span className="muted hide-mobile" style={{ fontSize: 13 }}>Cliquez sur un poste pour voir son écran · trait noir = attendu maintenant</span>
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
  OK: 'var(--green)', SECURITE: 'var(--red)', QUALITE: 'var(--red)', RYTHME: 'var(--amber)', CAMERA: 'var(--amber)', OBJET: 'var(--amber)',
};

const PAGE_SIZE = 6;

/**
 * Tableau des postes : une ligne par poste, dans l'ordre physique de la cellule, 6 par page.
 * Filtres : état du poste et recherche par nom (« P06 », « 6 »…).
 * Toute la ligne ouvre l'écran du poste (clic ou Entrée) ; l'icône ouvre l'historique.
 */
function StationTable({ stations, alerts }: { stations: StationSummary[]; alerts: Alert[] }) {
  const nav = useNavigate();
  const [status, setStatus] = useState<StationStatus | 'ALL'>('ALL');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);

  const q = query.trim().toUpperCase().replace(/^P0?/, '');
  const filtered = stations.filter((s) =>
    (status === 'ALL' || s.status === status) && (!q || shortId(s.id).replace(/^P0?/, '').startsWith(q)));
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const shown = filtered.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);
  // Un filtre qui change ramène à la première page.
  const onStatus = (v: StationStatus | 'ALL') => { setStatus(v); setPage(0); };
  const onQuery = (v: string) => { setQuery(v); setPage(0); };
  const present = (Object.keys(STATUS) as StationStatus[]).filter((k) => stations.some((s) => s.status === k));

  const th = { padding: '8px 10px', fontSize: 12, letterSpacing: '0.08em', fontWeight: 600, textAlign: 'left' as const };
  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        <input
          aria-label="Rechercher un poste"
          placeholder="Poste (ex. P06)"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          style={{ height: 38, width: 170, borderRadius: 10, border: '2px solid var(--line-strong)', padding: '0 12px', fontFamily: 'var(--font)', fontSize: 15 }}
        />
        <FilterChip active={status === 'ALL'} onClick={() => onStatus('ALL')}>Tous · {stations.length}</FilterChip>
        {present.map((k) => (
          <FilterChip key={k} active={status === k} onClick={() => onStatus(k)}>
            <span style={{ width: 9, height: 9, borderRadius: 5, background: DOT[k] }} />
            {STATUS[k][0]} · {stations.filter((s) => s.status === k).length}
          </FilterChip>
        ))}
      </div>

    <div style={{ overflowX: 'auto' }}>
      <table className="station-table" style={{ width: '100%', borderCollapse: 'collapse', minWidth: 860 }}>
        <thead>
          <tr className="muted">
            <th style={th}>POSTE</th>
            <th style={th}>ÉTAT</th>
            <th style={{ ...th, width: '26%' }}>AVANCEMENT DU SHIFT</th>
            <th style={th}>RYTHME</th>
            <th style={{ ...th, textAlign: 'right' }}>KO</th>
            <th style={th}>ALERTE EN COURS</th>
            <th style={th}><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {shown.map((s) => {
            const delta = s.good - s.expectedNow;
            const stAlerts = alerts.filter((a) => a.stationId === s.id);
            const hot = s.status === 'SECURITE' || s.status === 'QUALITE';
            const open = () => nav(stationScreenUrl(s.id, s.status));
            return (
              <tr
                key={s.id}
                tabIndex={0}
                onClick={open}
                onKeyDown={(e) => { if (e.key === 'Enter') open(); }}
                aria-label={`Poste ${shortId(s.id)} : ${STATUS[s.status][0]}, ${deltaText(delta, true)}. Ouvrir l’écran du poste`}
                style={{ boxShadow: hot ? 'inset 4px 0 0 var(--red)' : undefined }}
              >
                <td style={{ padding: '12px 10px' }}><span className="cond" style={{ fontWeight: 700, fontSize: 22 }}>{shortId(s.id)}</span></td>
                <td>
                  <span className="row" style={{ gap: 8, fontWeight: 600, fontSize: 14 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 5, background: DOT[s.status], flexShrink: 0 }} />{STATUS[s.status][0]}
                  </span>
                </td>
                <td>
                  <div className="row" style={{ gap: 10 }}>
                    <div className="track grow" style={{ height: 10, overflow: 'visible' }}>
                      <div className="fill" style={{ width: `${(s.good / s.target) * 100}%`, background: delta >= 0 ? 'var(--green)' : 'var(--amber)' }} />
                      <div style={{ position: 'absolute', left: `${(s.expectedNow / s.target) * 100}%`, top: -4, width: 3, height: 18, borderRadius: 2, background: 'var(--navy)' }} />
                    </div>
                    <span className="muted" style={{ fontSize: 13, width: 78, textAlign: 'right', whiteSpace: 'nowrap' }}>{s.good} / {fmt(s.target)}</span>
                  </div>
                </td>
                <td style={{ fontWeight: 700, fontSize: 15, whiteSpace: 'nowrap', color: delta < 0 ? 'var(--red-text)' : 'var(--green-text)' }}>{deltaText(delta, true)}</td>
                <td style={{ textAlign: 'right', fontWeight: 600 }}>{s.ko}</td>
                <td style={{ fontSize: 14, maxWidth: 260 }}>
                  {stAlerts.length
                    ? <span style={{ display: 'block', fontWeight: 600, color: 'var(--red-text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={stAlerts.map((a) => a.title).join(' · ')}>{stAlerts[0].title}{stAlerts.length > 1 ? ` (+${stAlerts.length - 1})` : ''}</span>
                    : <span className="muted">–</span>}
                </td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap', paddingRight: 6 }}>
                  <Link to={stationHistoryUrl(s.id)} onClick={(e) => e.stopPropagation()} className="icon-btn" title="Historique du shift" aria-label={`Historique du poste ${shortId(s.id)}`}>
                    <Icon d={ICONS.log} size={18} />
                  </Link>
                  <span className="muted" aria-hidden="true" style={{ fontSize: 22, marginLeft: 10 }}>›</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!shown.length && <div className="muted" style={{ padding: '18px 10px' }}>Aucun poste ne correspond au filtre.</div>}
    </div>

      <div className="between" style={{ alignItems: 'center' }}>
        <span className="muted" style={{ fontSize: 13 }}>
          {filtered.length ? `Postes ${current * PAGE_SIZE + 1} à ${current * PAGE_SIZE + shown.length} sur ${filtered.length}` : ''}
          {filtered.length !== stations.length ? ` (filtre actif sur ${stations.length})` : ''}
        </span>
        {pages > 1 && (
          <nav className="row" aria-label="Pages du tableau" style={{ gap: 6 }}>
            <button className="page-btn" disabled={current === 0} onClick={() => setPage(current - 1)} aria-label="Page précédente">‹</button>
            {Array.from({ length: pages }, (_, i) => (
              <button key={i} className="page-btn" aria-current={i === current ? 'page' : undefined} onClick={() => setPage(i)}>{i + 1}</button>
            ))}
            <button className="page-btn" disabled={current === pages - 1} onClick={() => setPage(current + 1)} aria-label="Page suivante">›</button>
          </nav>
        )}
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
        {a.acknowledgedBy && <span className="pill pill-green">Pris en charge · {a.acknowledgedBy}</span>}
        <span style={{ flex: 1 }} />
        <span className="muted" style={{ fontSize: 13 }}>{a.reportedByOperator ? 'signalé par l’opérateur' : ''}</span>
      </div>
      <span style={{ fontSize: 16, fontWeight: 700 }}>{a.title}</span>
      <span className="muted" style={{ fontSize: 14 }}>{a.detail}</span>
      <span style={{ fontSize: 14, fontWeight: 600 }}>Shift {a.shift} · {a.when}</span>
      {a.action === 'NONE' && <span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>Pour information : aucune validation demandée</span>}
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {!a.acknowledgedBy && <button className="btn btn-primary grow" onClick={onAcknowledge}>Je m’en occupe</button>}
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
