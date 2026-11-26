import { useState, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  activeAlert, displayVerdict, industrial, latest, ratePct, stationLabel,
  type Alert, type EdgeEvent, type Kpi as KpiData, type Part, type Station,
} from '../../api/industrial';
import { ProgressRing } from '../../components/charts';
import { Clock, Icon, ICONS, Kpi, Loading, TopBar } from '../../components/ui';
import { HovisLogo } from '../../components/brand';
import { useApi } from '../../hooks/useApi';

const shortTime = (value: string) => new Date(value).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
const number = (value: number | null | undefined) => value == null ? '—' : Math.round(value).toLocaleString('fr-FR');
const verdictColor = (verdict: string) => verdict === 'OK' ? 'var(--green)' : verdict === 'NOK' || verdict === 'ERROR' ? 'var(--red)' : 'var(--amber)';

function Problem({ children }: { children: ReactNode }) {
  return <div className="card pill-red" style={{ padding: 18, color: 'var(--red-text)' }}>{children}</div>;
}

function NetworkState({ error, hasData }: { error: string | null; hasData: boolean }) {
  if (!error) return null;
  return <Problem>{hasData ? 'Connexion interrompue · dernières données reçues. ' : 'Données indisponibles. '}{error}</Problem>;
}

function StationSelect({ stations, value, choose }: { stations: Station[]; value: string; choose: (id: string) => void }) {
  return <label className="row" style={{ gap: 8, fontWeight: 600 }}>Poste
    <select aria-label="Choisir un poste" value={value} onChange={(e) => choose(e.target.value)} className="btn" style={{ background: '#fff', color: 'var(--ink)' }}>
      {stations.map((station) => <option key={station.station_id} value={station.station_id}>{stationLabel(station)}</option>)}
    </select>
  </label>;
}

function LiveBadge({ simulated }: { simulated?: boolean }) {
  return <span className="pill pill-amber">{simulated ? 'Simulation en direct' : 'Données industrielles en direct'}</span>;
}

function AlertList({ alerts, actions = false, reload }: { alerts: Alert[]; actions?: boolean; reload?: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const perform = async (alert: Alert, action: 'acknowledge' | 'validate' | 'reject' | 'resolve') => {
    setBusy(alert.alert_id);
    setError('');
    try { await industrial.alertAction(alert.alert_id, action); reload?.(); }
    catch (cause) { setError(String(cause)); }
    finally { setBusy(null); }
  };
  return <div className="col" style={{ gap: 10 }}>
    {error && <Problem>{error}</Problem>}
    {alerts.length === 0 && <div className="muted">Aucune alerte reçue pour ce poste ou cette période.</div>}
    {alerts.map((alert) => <div key={alert.alert_id} className="card col" style={{ gap: 6, border: `2px solid ${alert.severity === 'critical' ? 'var(--red)' : 'var(--line)'}` }}>
      <div className="between"><b>{alert.station_id} · {alert.title}</b><span className="pill pill-blue">{alert.status}</span></div>
      <span className="muted">{alert.use_case ?? alert.alert_type} · {alert.occurrences} observation(s) · {shortTime(alert.last_seen_at)}{alert.simulated ? ' · synthétique' : ''}</span>
      {actions && <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {alert.status === 'open' && <button disabled={busy === alert.alert_id} className="btn btn-soft" onClick={() => perform(alert, 'acknowledge')}>Acquitter</button>}
        {(alert.status === 'open' || alert.status === 'acknowledged') && <>
          <button disabled={busy === alert.alert_id} className="btn btn-primary" onClick={() => perform(alert, 'validate')}>Valider</button>
          <button disabled={busy === alert.alert_id} className="btn btn-ghost" onClick={() => perform(alert, 'reject')}>Rejeter</button>
        </>}
        {(alert.status === 'open' || alert.status === 'acknowledged' || alert.status === 'validated') && <button disabled={busy === alert.alert_id} className="btn btn-dark" onClick={() => perform(alert, 'resolve')}>Résoudre</button>}
        <Link className="btn btn-soft" to={`/superviseur/poste/${encodeURIComponent(alert.station_id)}`}>Voir le poste</Link>
      </div>}
    </div>)}
  </div>;
}

type OperatorData = { station: Station; part: Part | null; alerts: Alert[]; kpi: KpiData };

export function LiveOperator() {
  const [params, setParams] = useSearchParams();
  const { data: stations, error: stationsError } = useApi(industrial.stations, [], 2000);
  const requested = params.get('station');
  const selected = stations?.find((station) => station.station_id === requested)?.station_id ?? stations?.[0]?.station_id;
  const { data, error, reload } = useApi<OperatorData | null>(async () => {
    if (!selected) return null;
    const [station, parts, alerts, kpi] = await Promise.all([
      industrial.station(selected), industrial.edgeParts(selected), industrial.alerts(selected), industrial.kpi(selected),
    ]);
    return { station, part: latest(parts), alerts, kpi };
  }, [selected], 2000);
  const [newVerdict, setNewVerdict] = useState<'' | 'OK' | 'NOK'>('');
  const [reason, setReason] = useState('');
  const [inspected, setInspected] = useState(false);
  const [actionError, setActionError] = useState('');
  const [actionDone, setActionDone] = useState('');
  const choose = (stationId: string) => setParams({ station: stationId });

  const correct = async (event: FormEvent) => {
    event.preventDefault();
    if (!data?.part || data.station.station_id !== selected || !newVerdict || newVerdict === data.part.effective_verdict) return;
    setActionError(''); setActionDone('');
    try {
      await industrial.correct(data.part, newVerdict, reason, inspected);
      setActionDone('Correction enregistrée · l’action physique sur la pièce reste distincte.');
      setReason(''); setNewVerdict(''); reload();
    } catch (cause) { setActionError(String(cause)); }
  };
  if (!stations && !stationsError) return <Loading />;
  if (!stations?.length) return <div className="screen"><TopBar title="POSTE" /><main className="page-sup"><NetworkState error={stationsError ?? 'Aucun poste disponible dans le Core.'} hasData={false} /></main></div>;
  const current = data?.station.station_id === selected ? data : null;
  const station = current?.station;
  const part = current?.part;
  const shift = station?.current_shift;
  const active = current?.alerts.filter(activeAlert) ?? [];
  const target = shift?.kpi.target_parts ?? null;
  const expected = shift?.kpi.expected_ok_parts_by_now ?? null;
  const camera = station?.equipment.find((item) => item.equipment_type === 'camera');
  return <div className="screen" style={{ background: part && part.effective_verdict !== 'OK' ? 'var(--red-tint)' : 'var(--op-bg)' }}>
    <TopBar title={`POSTE ${selected}`} sub="Contrôle de production" right={<><LiveBadge simulated={station?.simulated} /><Clock iso={new Date().toISOString()} /></>} />
    <main className="col" style={{ padding: '20px 28px', gap: 16 }}>
      <StationSelect stations={stations} value={selected!} choose={choose} />
      <NetworkState error={error ?? stationsError} hasData={!!current} />
      {station && <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
        <span className={`pill ${station.online ? 'pill-green' : 'pill-red'}`}>{station.online ? 'Poste actif récemment' : 'Aucun événement récent'}</span>
        <span className="pill pill-blue">Shift {shift?.shift.name ?? 'non renseigné'}</span>
        <span className="pill pill-blue">Caméra {camera?.status ?? 'inconnue'}</span>
      </div>}
      <div className="row stack-mobile" style={{ gap: 18, alignItems: 'stretch' }}>
        <section className="card-op col" style={{ flex: 1, minWidth: 290, gap: 14, padding: 22 }}>
          <span className="label-caps">Dernière pièce</span>
          {part ? <>
            <div className="num" style={{ fontSize: 76, color: verdictColor(part.effective_verdict) }}>{displayVerdict(part.effective_verdict)}</div>
            <span>Verdict initial : <b>{displayVerdict(part.predicted_verdict)}</b> · verdict effectif : <b>{displayVerdict(part.effective_verdict)}</b></span>
            <span>Score d’anomalie : <b>{part.prediction ? ratePct(part.prediction.score) : 'indisponible'}</b> (plus haut = plus de risque)</span>
            <span className="muted">Cycle {part.cycle_id} · {shortTime(part.created_at)} · modèle {part.prediction?.model_version ?? 'indisponible'}</span>
            <span className="muted">Image et nombre de joints indisponibles. Disposition physique : {part.disposition === 'UNKNOWN' ? 'non renseignée' : part.disposition}.</span>
          </> : <div className="muted">Aucune pièce produite sur ce poste.</div>}
        </section>
        <section className="card-op col" style={{ flex: 1, minWidth: 290, gap: 15, padding: 22 }}>
          <span className="label-caps">Production du poste · 8 dernières heures</span>
          {target != null && target > 0 && expected != null && <ProgressRing value={shift?.kpi.ok_parts ?? 0} target={target} expected={expected} size={200} />}
          <div className="grid-3">
            <Kpi label="Pièces bonnes" value={current?.kpi.ok_parts ?? '—'} />
            <Kpi label="Pièces KO" value={current?.kpi.nok_parts ?? '—'} />
            <Kpi label="Objectif shift" value={target == null ? '—' : target} />
          </div>
          <span>Cadence : {number(current?.kpi.actual_total_rate_per_hour)} pièces/h · taux KO : {ratePct(current?.kpi.nok_rate ?? null)}</span>
          {target == null && <span className="muted">Aucun objectif de shift actif renseigné.</span>}
        </section>
      </div>
      <div className="grid-3">
        <Status label="Sécurité" alert={active.find((item) => item.use_case === 'safety')} />
        <Status label="Poste de travail" alert={active.find((item) => item.use_case === 'workstation')} />
        <Status label="Qualité" alert={active.find((item) => item.use_case === 'quality')} known={!!part} ok={part?.effective_verdict === 'OK'} />
      </div>
      <section className="card col" style={{ gap: 10 }}><h2 className="h2">Alertes du poste</h2>{current ? <AlertList alerts={active} /> : <span className="muted">Données indisponibles.</span>}</section>
      {part && <form onSubmit={correct} className="card col" style={{ gap: 10 }}>
        <h2 className="h2">Correction du verdict après inspection humaine</h2>
        <span className="muted">La correction logicielle ne déplace pas et ne libère pas la pièce.</span>
        <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
          <select aria-label="Nouveau verdict" className="btn" value={newVerdict} required onChange={(e) => setNewVerdict(e.target.value as 'OK' | 'NOK')}><option value="">Nouveau verdict</option><option value="OK">OK</option><option value="NOK">KO</option></select>
          <input aria-label="Motif de correction" className="btn grow" style={{ minWidth: 220, background: '#fff' }} value={reason} minLength={3} maxLength={500} required placeholder="Motif de la correction" onChange={(e) => setReason(e.target.value)} />
          <label><input type="checkbox" checked={inspected} onChange={(e) => setInspected(e.target.checked)} /> Pièce inspectée physiquement</label>
          <button className="btn btn-primary" disabled={!newVerdict || newVerdict === part.effective_verdict || ((part.effective_verdict === 'HOLD' || part.effective_verdict === 'ERROR') && !inspected)}>Enregistrer</button>
        </div>
        {actionError && <Problem>{actionError}</Problem>}{actionDone && <span className="pill pill-green">{actionDone}</span>}
      </form>}
      <button className="btn" disabled title="Endpoint transactionnel indisponible">Signaler un problème · indisponible en live</button>
    </main>
  </div>;
}

function Status({ label, alert, known = false, ok = false }: { label: string; alert?: Alert; known?: boolean; ok?: boolean }) {
  const state = alert ? 'Alerte' : known ? ok ? 'Conforme' : 'À vérifier' : 'Inconnu';
  return <div className="card row" style={{ gap: 12, border: `2px solid ${alert ? 'var(--red)' : 'var(--line)'}` }}>
    <Icon d={alert ? ICONS.shieldAlert : ICONS.shield} size={30} />
    <div className="col"><b>{label}</b><span className="muted">{state}{alert?.simulated ? ' · observation synthétique' : ''}</span></div>
  </div>;
}

type WorkshopData = { stations: Station[]; kpis: Record<string, KpiData>; global: KpiData; alerts: Alert[] };

async function workshop(): Promise<WorkshopData> {
  const [stations, global, alerts] = await Promise.all([
    industrial.stations(), industrial.kpi(), industrial.alerts(),
  ]);
  const kpis: Record<string, KpiData> = {};
  // Bounded groups avoid an unbounded burst against Core when more stations are added.
  for (let offset = 0; offset < stations.length; offset += 4) {
    const group = stations.slice(offset, offset + 4);
    const values = await Promise.all(group.map((station) => industrial.kpi(station.station_id)));
    group.forEach((station, index) => { kpis[station.station_id] = values[index]; });
  }
  return { stations, kpis, global, alerts };
}

export function LiveSupervisor() {
  const { data, error, reload } = useApi(workshop, [], 4000);
  const [tab, setTab] = useState<'overview' | 'prod' | 'alerts' | 'equip'>('overview');
  if (!data && !error) return <Loading />;
  const stations = data?.stations ?? [];
  const alerts = data?.alerts.filter(activeAlert) ?? [];
  const cells = [...new Set(stations.map((station) => station.cell))];
  const knownCameras = stations.flatMap((station) => station.equipment.filter((item) => item.equipment_type === 'camera'));
  return <div className="screen">
    <TopBar title="Atelier injection" sub={`${stations.length} postes · données Core`} right={<LiveBadge simulated={stations.some((station) => station.simulated)} />} />
    <nav className="tabs" role="tablist">
      {([['overview', 'Vue d’ensemble'], ['prod', 'Production'], ['alerts', 'Alertes'], ['equip', 'Équipements']] as const).map(([key, label]) =>
        <button className="tab" role="tab" aria-selected={tab === key} key={key} onClick={() => setTab(key)}>{label}{key === 'alerts' ? ` · ${alerts.length}` : ''}</button>)}
    </nav>
    <main className="col page-sup" style={{ padding: '20px 24px', gap: 16, flex: 1 }}>
      <NetworkState error={error} hasData={!!data} />
      {tab === 'overview' && <>
        <div className="grid-5">
          <Kpi label="Pièces bonnes · 8 h" value={data?.global.ok_parts ?? '—'} />
          <Kpi label="Pièces KO · 8 h" value={data?.global.nok_parts ?? '—'} />
          <Kpi label="Taux KO · 8 h" value={ratePct(data?.global.nok_rate ?? null)} />
          <Kpi label="Alertes actives" value={data ? alerts.length : '—'} />
          <Kpi label="Postes sans événement récent" value={data ? stations.filter((station) => !station.online).length : '—'} />
        </div>
        <div className="grid-3">{cells.map((cell) => {
          const members = stations.filter((station) => station.cell === cell);
          const good = members.reduce((sum, station) => sum + (data?.kpis[station.station_id]?.ok_parts ?? 0), 0);
          const target = members.reduce((sum, station) => sum + (station.current_shift?.kpi.target_parts ?? 0), 0);
          return <button className="card col" key={cell} onClick={() => setTab('prod')} style={{ textAlign: 'left', border: 'none', gap: 8 }}>
            <b className="cond" style={{ fontSize: 24 }}>Cellule {cell}</b>
            <span className="num" style={{ fontSize: 36 }}>{good} pièces bonnes</span>
            <span className="muted">{members.length} postes · objectif actif {target || 'non renseigné'}</span>
          </button>;
        })}</div>
        <div className="card col"><h2 className="h2">Alertes récentes</h2>{data ? <AlertList alerts={alerts.slice(0, 4)} /> : <span className="muted">Données indisponibles.</span>}</div>
      </>}
      {tab === 'prod' && <>
        <div className="card col" style={{ gap: 10 }}><h2 className="h2">Production par poste · 8 dernières heures</h2>
          <span className="muted">Objectifs affichés seulement lorsqu’un shift actif les renseigne. « En ligne » mesure la fraîcheur des événements.</span>
          <div className="grid-3">{stations.map((station) => {
            const kpi = data?.kpis[station.station_id];
            const target = station.current_shift?.kpi.target_parts;
            const alert = alerts.some((item) => item.station_id === station.station_id);
            return <Link key={station.station_id} to={`/superviseur/poste/${encodeURIComponent(station.station_id)}`} className="card col" style={{ gap: 8, color: 'var(--ink)', border: `2px solid ${alert ? 'var(--red)' : 'var(--line)'}` }}>
              <b className="cond" style={{ fontSize: 23 }}>{station.station_id}</b>
              <span className={`pill ${station.online ? 'pill-green' : 'pill-red'}`}>{station.online ? 'Événement récent' : 'Hors ligne / inactif'}</span>
              <span>{kpi?.ok_parts ?? '—'} OK · {kpi?.nok_parts ?? '—'} KO · objectif {target ?? '—'}</span>
              <span className="muted">Cadence {number(kpi?.actual_total_rate_per_hour)} pièces/h · {station.simulated ? 'simulation' : 'source Edge'}</span>
            </Link>;
          })}</div>
        </div>
      </>}
      {tab === 'alerts' && <>
        <div className="between"><h2 className="h2">Épisodes actifs</h2><span className="muted">Validé reste actif jusqu’à résolution ; maintenance indisponible.</span></div>
        <AlertList alerts={alerts} actions reload={reload} />
      </>}
      {tab === 'equip' && <div className="card col" style={{ gap: 12 }}>
        <h2 className="h2">Équipements rapportés</h2>
        <span className="muted">{knownCameras.length} caméra(s) avec un état communiqué. Le nombre total installé n’est pas connu.</span>
        {stations.map((station) => <div key={station.station_id} className="between" style={{ borderBottom: '1px solid var(--line-soft)', padding: 8 }}>
          <b>{station.station_id}</b><span>{station.equipment.length ? station.equipment.map((item) => `${item.equipment_id} : ${item.status}`).join(' · ') : 'État non renseigné'}</span>
        </div>)}
      </div>}
    </main>
  </div>;
}

export function LiveCellule() {
  const [params, setParams] = useSearchParams();
  const { data: stations, error: stationsError } = useApi(industrial.stations, [], 2000);
  const selected = stations?.find((station) => station.station_id === params.get('station'))?.station_id ?? stations?.[0]?.station_id;
  const { data, error } = useApi(async () => {
    if (!selected) return null;
    const [station, alerts, parts] = await Promise.all([
      industrial.station(selected), industrial.alerts(selected), industrial.parts(selected, 1),
    ]);
    return { station, alerts: alerts.filter(activeAlert), part: latest(parts) };
  }, [selected], 2000);
  if (!stations && !stationsError) return <Loading />;
  if (!stations?.length) return <div className="screen"><NetworkState error={stationsError ?? 'Aucun poste disponible.'} hasData={false} /></div>;
  const current = data?.station.station_id === selected ? data : null;
  const safety = current?.alerts.find((item) => item.use_case === 'safety');
  const workstation = current?.alerts.find((item) => item.use_case === 'workstation');
  const quality = current?.part;
  const camera = current?.station.equipment.find((item) => item.equipment_type === 'camera');
  const tiles = [
    { title: 'Sécurité', issue: safety, state: safety ? 'Alerte' : 'Inconnu' },
    { title: 'Poste rangé', issue: workstation, state: workstation ? 'Alerte' : 'Inconnu' },
    { title: 'Qualité', issue: undefined, state: quality ? displayVerdict(quality.effective_verdict) : 'Inconnue', bad: quality ? quality.effective_verdict !== 'OK' : false, known: !!quality },
    { title: 'Caméra', issue: undefined, state: camera?.status ?? 'Inconnue', bad: camera ? camera.status !== 'ok' : false, known: !!camera },
  ];
  return <div style={{ minHeight: '100vh', background: 'var(--navy)', color: '#fff', padding: '36px 48px', display: 'flex', flexDirection: 'column', gap: 28 }}>
    <div className="row" style={{ gap: 16 }}><HovisLogo size={44} tone="light" /><span className="cond" style={{ fontSize: 40 }}>POSTE {selected}</span><span style={{ flex: 1 }} /><LiveBadge simulated={current?.station.simulated} /><Clock iso={new Date().toISOString()} /></div>
    <StationSelect stations={stations} value={selected!} choose={(id) => setParams({ station: id })} />
    <NetworkState error={error ?? stationsError} hasData={!!current} />
    <div className="grid-2" style={{ flex: 1, gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 24 }}>
      {tiles.map((tile) => {
        const bad = !!tile.issue || !!tile.bad;
        const good = !bad && !!tile.known;
        return <div key={tile.title} style={{ background: bad ? 'var(--red-deep)' : 'var(--navy-2)', border: `3px solid ${bad ? 'var(--red-on-navy)' : 'transparent'}`, borderRadius: 30, padding: 25, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 22 }}>
          <div style={{ flex: 1, width: 120, minHeight: 200, borderRadius: 60, background: bad ? 'var(--red)' : good ? 'var(--green)' : 'var(--amber)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Icon d={ICONS.shield} size={56} color="#fff" /></div>
          <span className="cond" style={{ fontWeight: 700, fontSize: 30, textAlign: 'center' }}>{tile.title} · {tile.state}</span>
          {tile.issue?.simulated && <span>Observation synthétique</span>}
        </div>;
      })}
    </div>
    <div className="between" style={{ color: 'var(--on-navy-muted)' }}><span>Voyants établis uniquement à partir des faits reçus.</span><span>Dernière pièce : {quality ? displayVerdict(quality.effective_verdict) : 'indisponible'}</span></div>
  </div>;
}

export function LivePosteDetail() {
  const navigate = useNavigate();
  const { id: stationId } = useParams();
  const { data: stations } = useApi(industrial.stations, [], 5000);
  const { data, error } = useApi(async () => {
    if (!stationId) return null;
    const [station, kpi, parts, events, alerts] = await Promise.all([
      industrial.station(stationId), industrial.kpi(stationId), industrial.parts(stationId, 100),
      industrial.events(stationId, 100), industrial.alerts(stationId),
    ]);
    return { station, kpi, parts, events, alerts };
  }, [stationId], 5000);
  if (!stationId) return <div className="screen"><Problem>Identifiant de poste manquant.</Problem></div>;
  if (!data && !error) return <Loading />;
  const current = data?.station.station_id === stationId ? data : null;
  const active = current?.alerts.filter(activeAlert) ?? [];
  return <div className="screen">
    <TopBar title={`Poste ${stationId}`} sub="Historique industriel disponible" right={<Link to="/superviseur" style={{ color: 'var(--on-navy-muted)' }}>← Atelier</Link>} />
    <main className="col" style={{ padding: '20px 24px', gap: 16 }}>
      <NetworkState error={error} hasData={!!current} />
      {stations && <StationSelect stations={stations} value={stationId} choose={(id) => navigate(`/superviseur/poste/${encodeURIComponent(id)}`)} />}
      <div className="grid-5">
        <Kpi label="Pièces bonnes · 8 h" value={current?.kpi.ok_parts ?? '—'} />
        <Kpi label="Pièces KO · 8 h" value={current?.kpi.nok_parts ?? '—'} />
        <Kpi label="Taux KO" value={ratePct(current?.kpi.nok_rate ?? null)} />
        <Kpi label="Cadence" value={`${number(current?.kpi.actual_total_rate_per_hour)} / h`} />
        <Kpi label="Objectif shift actif" value={current?.station.current_shift?.kpi.target_parts ?? '—'} />
      </div>
      <div className="card col"><h2 className="h2">État du poste</h2>
        <span>{current ? current.station.online ? 'Événement récent' : 'Aucun événement récent' : 'État inconnu'} · {current?.station.simulated ? 'simulation' : 'source Edge ou inconnue'}</span>
        <span>Équipement : {current?.station.equipment.map((item) => `${item.equipment_id} ${item.status}`).join(' · ') || 'inconnu'}</span>
      </div>
      <div className="grid-2">
        <section className="card col"><h2 className="h2">Dernières pièces · maximum 100</h2>
          {current?.parts.map((part) => <div key={part.part_id} className="between" style={{ borderBottom: '1px solid var(--line-soft)', padding: 7 }}><span>{shortTime(part.created_at)} · {part.cycle_id}</span><b>{displayVerdict(part.effective_verdict)}{part.correction_count ? ' · corrigée' : ''}</b></div>)}
          {!current?.parts.length && <span className="muted">{current ? 'Aucune pièce disponible.' : 'Données indisponibles.'}</span>}
        </section>
        <section className="card col"><h2 className="h2">Événements · 100 plus récents</h2>
          {current?.events.map((event: EdgeEvent) => <div key={event.event_id} className="between" style={{ borderBottom: '1px solid var(--line-soft)', padding: 7 }}><span>{shortTime(event.occurred_at)} · {event.event_type}</span><span>{event.simulated ? 'synthétique' : event.use_case ?? 'Edge'}</span></div>)}
          {!current?.events.length && <span className="muted">{current ? 'Aucun événement disponible.' : 'Données indisponibles.'}</span>}
        </section>
      </div>
      <section className="card col"><h2 className="h2">Alertes du poste</h2>{current ? <AlertList alerts={active} /> : <span className="muted">Données indisponibles.</span>}</section>
    </main>
  </div>;
}
