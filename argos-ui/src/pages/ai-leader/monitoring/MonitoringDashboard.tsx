import { useMemo, useState, type ReactNode } from 'react';
import { Icon, ICONS } from '../../../components/ui';
import { monitoring, type CatalogRow, type DataKind, type DriftStatus, type Filters, type Snapshot } from '../../../api/monitoring';
import { Loading, Unavailable } from '../common';
import { errText, useStore } from '../data';
import '../training/training.css';
import { Chip, Donut, Kpi, SearchField, SelectField } from '../ui';
import { HBars, Series } from './charts';
import ModelDetail from './ModelDetail';
import './monitoring.css';
import {
  day, DECISIONS, driftHelp, driftLabel, DriftChip, dt, ms, OriginChip, PERIODS, periodLabel, shortKey, SourceChip, SourceLine, startOf,
  useAlerts, useCaseFr, useCatalog, useHistory, useInferences, useMonParams, useSummary, USE_CASES,
} from './shared';

const PAGE = 10;
const DRIFT_COLORS: Partial<Record<DriftStatus, string>> = {
  alert: 'var(--red)', watch: 'var(--amber)', stable: 'var(--green)', reference_absent: 'var(--line-strong)',
  insufficient_reference: '#e9b25c', insufficient_current: '#e9b25c', incompatible: 'var(--red-light)', mixed_data: '#e9b25c', no_production_data: 'var(--track)',
};

/* Monitoring (DBX-07C) : vue globale sans modèle présélectionné, catalogue des modèles, détail
   à la demande. Toutes les données viennent des API Monitoring DBX-07B (aucune série fictive). */
export default function MonitoringDashboard() {
  const store = useStore();
  const nav = useMonParams();
  const real = useSummary('real');
  const [origin, setOrigin] = useState<DataKind | null>(null);
  const [useCase, setUseCase] = useState('');
  const [modelKey, setModelKey] = useState('');
  const [version, setVersion] = useState('');
  const [station, setStation] = useState('');
  const [cell, setCell] = useState('');
  const [period, setPeriod] = useState('all');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  // Default origin: real production when it exists, otherwise the simulation (never both).
  const kind: DataKind | null = origin ?? (real.data ? (real.data.inferences > 0 ? 'real' : 'simulated') : real.error ? 'simulated' : null);
  const filters: Filters | null = kind ? { data_kind: kind, use_case: useCase || undefined, model_key: modelKey || undefined, version: version || undefined, station: station || undefined, start: startOf(period) } : null;
  const inf = useInferences(filters);
  const cat = useCatalog(filters);
  const alerts = useAlerts();
  const hist = useHistory(kind);

  const rows = cat.data ?? [];
  const op = inf.data;
  const stationsInScope = useMemo(() => Array.from(new Set((op?.groups ?? []).map((g) => g.station_id))).sort(), [op]);
  const cells = Array.from(new Set((op?.model_states ?? []).map((s) => s.cell).filter((c): c is string => !!c))).sort();
  const stationOptions = (op?.model_states ?? []).filter((s) => !cell || s.cell === cell).map((s) => s.station_id).sort();
  const modelRow = rows.find((r) => r.model_key === modelKey);
  const scopeText = [useCase ? useCaseFr(useCase) : 'tous cas d’usage', modelKey ? shortKey(modelKey) : 'tous modèles', version ? `v${version}` : null, station || (cell ? `cellule ${cell}` : 'tous postes')].filter(Boolean).join(' · ');
  const availability = inf.error ? 'unavailable' : op?.status;

  const openAlerts = (alerts.data ?? []).filter((a) => a.state === 'open');
  const driftAlerts = openAlerts.filter((a) => a.kind === 'drift' && a.data_kind === kind && (!modelKey || a.model_key === modelKey) && (!version || a.model_version === version));
  const operational = rows.filter((r) => r.source === 'operational' && r.n_inferences > 0 && (!modelKey || r.model_key === modelKey));
  const investigate = rows.filter((r) => r.needs_investigation && (!modelKey || r.model_key === modelKey));

  const meta = (extra?: ReactNode) => (
    <span className="mon-kpi-meta">
      <span>{scopeText}</span><span>· {periodLabel(period)}</span>
      {kind && <OriginChip kind={kind} />}<SourceChip status={availability} />{extra}
    </span>
  );
  const v = (x: ReactNode, res: { loading: boolean; error: string | null }) => (res.error ? '—' : res.loading ? '…' : x);

  const collect = async () => {
    if (!window.confirm('Lancer une collecte explicite ?\n\nElle enregistre localement les instantanés journaliers et met à jour les alertes MLOps. Aucune action Databricks, aucun réentraînement.')) return;
    setBusy(true);
    try {
      const r = await monitoring.collect();
      setNote(`Collecte du ${dt(r.collected_at)} : ${r.snapshots_written} instantané(s), ${r.open_alerts} alerte(s) ouverte(s), ${r.resolved_alerts} résolue(s)${r.partial ? ' — données partielles' : ''}.`);
      store.invalidate('mon:');
    } catch (e) {
      setNote(`Collecte impossible : ${errText(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="tf">
      <header className="card tf-hero">
        <div className="tf-hero-title">
          <span className="tf-hero-icon"><Icon d={ICONS.monitor} size={24} /></span>
          <div><h1 className="h2">Monitoring — Surveillance des modèles</h1>
            <p className="muted">Activité opérationnelle, performances hors ligne, dérives statistiques et retours humains.</p></div>
        </div>
        <div className="row" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <SourceLine sources={op?.sources} res={inf} />
          {kind && <OriginChip kind={kind} />}
          <button className="btn btn-ghost" disabled={busy} onClick={collect} title="Écriture locale explicite : instantanés et alertes">Collecter maintenant</button>
          <button className="btn btn-ghost" disabled={inf.refreshing} onClick={() => store.invalidate('mon:')}>Actualiser</button>
        </div>
      </header>
      {note && <div className="mon-banner navy">{note}<button className="btn" style={{ background: 'none', height: 'auto', padding: 0, marginLeft: 'auto' }} onClick={() => setNote('')}>×</button></div>}

      <div className="card tf-filters" style={{ padding: 12 }}>
        <SelectField label="Origine des données" icon="none" value={kind ?? ''} onChange={(x) => setOrigin(x as DataKind)}
          options={[['real', `Production réelle${real.data ? ` (${real.data.inferences} inf.)` : ''}`], ['simulated', 'Données simulées']]} />
        <SelectField label="Cas d’usage" allLabel="Tous les cas d’usage" value={useCase} onChange={(x) => { setUseCase(x); setModelKey(''); setVersion(''); }} options={USE_CASES} />
        <SelectField label="Modèle" allLabel="Tous les modèles" value={modelKey} onChange={(x) => { setModelKey(x); setVersion(''); }}
          options={rows.map((r) => [r.model_key, `${r.name}${r.source === 'registry' ? ' (registre)' : ' (non associé UC)'}`])} />
        <SelectField label="Version" allLabel="Toutes les versions" value={version} onChange={setVersion} options={(modelRow?.versions ?? []).map((x) => [x, `v${x}`])} />
        <SelectField label="Cellule" allLabel={cells.length ? 'Toutes les cellules' : 'Cellule non renseignée'} value={cell} onChange={(x) => { setCell(x); setStation(''); }} options={cells.map((c) => [c, c])} />
        <SelectField label="Poste" allLabel="Tous les postes" value={station} onChange={setStation} options={stationOptions.map((s) => [s, s])} />
        <SelectField label="Période" icon="none" value={period} onChange={setPeriod} options={PERIODS} />
      </div>

      {kind === 'simulated' && (
        <div className="mon-banner">
          <Chip tone="amber">Données simulées</Chip>
          Les métriques affichées proviennent de la simulation des postes{real.data ? ` (production réelle : ${real.data.inferences} inférence${real.data.inferences > 1 ? 's' : ''})` : ''}. Elles ne sont jamais mélangées avec la production réelle et ne mesurent pas la performance en production.
        </div>
      )}
      {op?.status === 'partial' && <div className="mon-banner">Agrégation partielle : l’API Core est limitée à 500 éléments par poste. Les chiffres ne sont pas exhaustifs.</div>}
      {inf.error && <Unavailable tone="red">Données opérationnelles indisponibles : {inf.error}</Unavailable>}
      {op?.status === 'unavailable' && <Unavailable tone="red">Core indisponible : {op.sources[0]?.detail ?? 'aucune réponse'}. Aucun chiffre n’est affiché à la place.</Unavailable>}

      <div className="mon-kpis">
        <Kpi icon="layers" label="Modèles surveillés" value={v(operational.length, cat)} hint={meta(<span>{rows.filter((r) => r.source === 'registry').length} modèle(s) du registre sans inférence associée</span>)} />
        <Kpi icon="grid" label="Postes concernés" value={v(stationsInScope.length, inf)} hint={meta()} />
        <Kpi icon="bars" label="Inférences" value={v(op?.total.n_inferences.toLocaleString('fr-FR'), inf)} hint={meta(<span>{op ? `${op.total.n_parts} cycle(s) / pièce(s) inspecté(s)` : ''}</span>)} />
        <Kpi icon="play" label="Latence P95" value={v(ms(op?.total.latency_ms.p95), inf)} hint={meta(<span>{op ? `P50 ${ms(op.total.latency_ms.p50)}` : ''}</span>)} />
        <Kpi icon="warn" label="Alertes de dérive" value={v(driftAlerts.length, alerts)} tone={driftAlerts.length ? 'red' : undefined}
          hint={meta(<span>{hist.data?.collections[0] ? `dernière collecte ${dt(hist.data.collections[0].at)}` : 'aucune collecte'}</span>)} />
        <Kpi icon="shieldAlert" label="À investiguer" value={v(investigate.length, cat)} tone={investigate.length ? 'red' : undefined}
          hint={meta(<span>alerte ouverte ou dérive ≥ seuil de surveillance</span>)} />
      </div>

      <div className="mon-charts">
        <section className="card mon-card">
          <h3>Répartition des décisions</h3><span className="sub">Décisions de l’IA sur les inférences filtrées</span>
          {inf.loading ? <Loading /> : op && op.total.n_inferences > 0
            ? <Donut centerLabel="inférences" items={DECISIONS.map((d) => ({ label: d.label, count: op.total.decision_counts[d.id] ?? 0, color: d.color }))} />
            : <div className="mon-empty">Aucune inférence pour ces filtres.</div>}
        </section>
        <VolumeChart snapshots={hist.data?.snapshots} filters={filters} loading={hist.loading} error={hist.error} />
        <LatencyChart snapshots={hist.data?.snapshots} filters={filters} />
        <section className="card mon-card">
          <h3>État de la surveillance statistique</h3><span className="sub">Par modèle, dernière version observée, contre sa référence figée</span>
          {cat.loading ? <Loading /> : <HBars items={(['alert', 'watch', 'stable', 'reference_absent', 'insufficient_reference', 'insufficient_current', 'incompatible', 'mixed_data', 'no_production_data'] as DriftStatus[])
            .map((s) => ({ label: driftLabel(s), count: rows.filter((r) => r.drift.status === s).length, color: DRIFT_COLORS[s] ?? 'var(--line-strong)', hint: driftHelp(s) }))
            .filter((i) => i.count > 0)} />}
          <span className="muted" style={{ fontSize: 12 }}>Seuils PSI configurés côté backend (0,1 surveillance · 0,2 alerte), minimum 100 observations de part et d’autre.</span>
        </section>
        <section className="card mon-card">
          <h3>Répartition des alertes</h3><span className="sub">Alertes MLOps ouvertes (distinctes des alertes Supervisor)</span>
          {alerts.loading ? <Loading /> : openAlerts.length
            ? <HBars items={Object.entries(openAlerts.reduce<Record<string, number>>((acc, a) => {
              const k = a.kind === 'drift' ? `Dérive · ${a.indicator} (${a.method})` : `Disponibilité · ${a.indicator}`;
              acc[k] = (acc[k] ?? 0) + 1;
              return acc;
            }, {})).map(([label, count]) => ({ label, count, color: label.startsWith('Dérive') ? 'var(--red)' : 'var(--amber)' }))} />
            : <div className="mon-empty">
              Aucune alerte ouverte.{' '}
              {rows.some((r) => r.drift.status === 'reference_absent') && `${rows.filter((r) => r.drift.status === 'reference_absent').length} modèle(s) sans référence : l’absence d’alerte ne signifie pas une stabilité. `}
              {rows.some((r) => r.drift.status.startsWith('insufficient')) && 'Des effectifs insuffisants empêchent aussi toute alerte fiable.'}
            </div>}
        </section>
      </div>

      <Catalog rows={rows} loading={cat.loading} error={cat.error} selected={nav.key} onOpen={(k) => nav.set({ key: k, tab: null })} detail={
        nav.key && kind ? <ModelDetail key={`${nav.key}:${kind}`} modelKey={nav.key} kind={kind} row={rows.find((r) => r.model_key === nav.key) ?? null} onClose={() => nav.set({ key: null, tab: null })} /> : null
      } />
    </div>
  );
}

function scopedSnapshots(snapshots: Snapshot[] | undefined, f: Filters | null): Snapshot[] {
  if (!snapshots || !f) return [];
  return snapshots.filter((s) => s.data_kind === f.data_kind && (!f.model_key || s.scope_key.startsWith(`${f.model_key}|`))
    && (!f.version || s.scope_key.includes(`|${f.version}|`)) && (!f.use_case || s.scope_key.includes(`:${f.use_case}:`))
    && (!f.start || s.window_end > f.start));
}

function VolumeChart({ snapshots, filters, loading, error }: { snapshots?: Snapshot[]; filters: Filters | null; loading: boolean; error: string | null }) {
  const rows = scopedSnapshots(snapshots, filters);
  const days = Array.from(new Set(rows.map((s) => s.window_start))).sort();
  const points = days.map((d) => ({ x: day(d), values: { Inférences: rows.filter((s) => s.window_start === d).reduce((n, s) => n + s.n_inferences, 0) } }));
  return (
    <section className="card mon-card">
      <h3>Volume d’inférences dans le temps</h3><span className="sub">Instantanés journaliers issus des collectes explicites{filters?.station ? ' (tous postes : le poste n’est pas une dimension des instantanés)' : ''}</span>
      {loading ? <Loading /> : error ? <Unavailable tone="red">Historique indisponible : {error}</Unavailable>
        : <Series points={points} series={[{ name: 'Inférences', color: 'var(--primary)' }]} format={(n) => n.toLocaleString('fr-FR')}
          empty="Aucun instantané collecté pour ces filtres : utilisez « Collecter maintenant » pour enregistrer l’historique (aucune série n’est inventée)." />}
    </section>
  );
}

function LatencyChart({ snapshots, filters }: { snapshots?: Snapshot[]; filters: Filters | null }) {
  const rows = scopedSnapshots(snapshots, filters);
  const days = Array.from(new Set(rows.map((s) => s.window_start))).sort();
  // Percentiles of different models cannot be combined: a day is plotted only for ONE scope.
  const points = days.map((d) => rows.filter((s) => s.window_start === d)).filter((r) => r.length === 1)
    .map(([s]) => ({ x: day(s.window_start), values: { P50: s.latency_ms.p50, P95: s.latency_ms.p95 } }));
  const multi = days.length > 0 && points.length === 0;
  return (
    <section className="card mon-card">
      <h3>Latences P50 et P95</h3><span className="sub">Par jour collecté, pour un seul modèle et une seule version</span>
      {multi
        ? <div className="col" style={{ gap: 8 }}>
          <div className="mon-empty">Les percentiles de plusieurs modèles ne s’additionnent pas : sélectionnez un modèle pour tracer l’évolution. Dernier jour collecté :</div>
          <table className="tf-table mon-table"><thead><tr><th>Modèle · version</th><th className="num">P50</th><th className="num">P95</th></tr></thead>
            <tbody>{rows.filter((s) => s.window_start === days[days.length - 1]).map((s) => (
              <tr key={s.snapshot_id} className="static"><td>{shortKey(s.scope_key.split('|')[0])} · v{s.scope_key.split('|')[1]}</td><td className="num">{ms(s.latency_ms.p50)}</td><td className="num">{ms(s.latency_ms.p95)}</td></tr>))}
            </tbody></table>
        </div>
        : <Series points={points} series={[{ name: 'P50', color: 'var(--primary-light)' }, { name: 'P95', color: 'var(--red)' }]} format={ms}
          empty="Aucun instantané collecté pour ces filtres." />}
    </section>
  );
}

function Catalog({ rows, loading, error, selected, onOpen, detail }: {
  rows: CatalogRow[]; loading: boolean; error: string | null; selected: string | null; onOpen: (key: string) => void; detail: ReactNode;
}) {
  const [query, setQuery] = useState('');
  const [source, setSource] = useState('');
  const [drift, setDrift] = useState('');
  const [sort, setSort] = useState('inferences');
  const [page, setPage] = useState(0);
  const filtered = useMemo(() => rows
    .filter((r) => (!source || r.source === source) && (!drift || r.drift.status === drift))
    .filter((r) => `${r.name} ${r.model_key} ${r.registry_link} ${r.use_case ?? ''}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
    .sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name) : sort === 'p95' ? (b.latency_p95 ?? -1) - (a.latency_p95 ?? -1)
      : sort === 'activity' ? (b.last_activity ?? '').localeCompare(a.last_activity ?? '') : b.n_inferences - a.n_inferences), [rows, source, drift, query, sort]);
  const visible = filtered.slice(page * PAGE, page * PAGE + PAGE);
  return (
    <div className={`tf-layout${detail ? '' : ' full'}`}>
      <section className="card tf-panel tf-catalog">
        <div className="between" style={{ gap: 10, flexWrap: 'wrap' }}>
          <h2 className="h2" style={{ fontSize: 21 }}>Catalogue des modèles</h2>
          <span className="muted" style={{ fontSize: 13 }}>{filtered.length} modèle(s)</span>
        </div>
        <div className="tf-filters">
          <SearchField placeholder="Rechercher (nom, clé, modèle Unity Catalog…)" value={query} onChange={(x) => { setQuery(x); setPage(0); }} />
          <SelectField label="Origine du modèle" allLabel="Registre et opérationnels" value={source} onChange={(x) => { setSource(x); setPage(0); }}
            options={[['registry', 'Registre Unity Catalog'], ['operational', 'Opérationnels non associés']]} />
          <SelectField label="État de dérive" allLabel="Tous les états" value={drift} onChange={(x) => { setDrift(x); setPage(0); }}
            options={Array.from(new Set(rows.map((r) => r.drift.status))).map((s) => [s, driftLabel(s)])} />
          <SelectField label="Tri" icon="sort" value={sort} onChange={setSort} options={[['inferences', 'Inférences'], ['activity', 'Dernière activité'], ['p95', 'Latence P95'], ['name', 'Nom']]} />
        </div>
        {loading && <Loading what="Lecture du catalogue de surveillance" />}
        {error && <Unavailable tone="red">Catalogue indisponible : {error}</Unavailable>}
        {!loading && !error && filtered.length === 0 && <Unavailable tone="grey">Aucun modèle pour ces critères.</Unavailable>}
        {visible.length > 0 && <div className="tf-table-wrap"><table className="tf-table mon-table"><thead><tr>
          <th>Modèle</th><th>Cas d’usage</th><th>Versions</th><th className="num">Postes</th><th className="num">Inférences</th>
          <th className="num opt">P95</th><th>Dérive</th><th className="num opt">Corrections</th><th className="opt">Action</th>
        </tr></thead><tbody>{visible.map((r) => (
          <tr key={r.model_key} className={selected === r.model_key ? 'selected' : ''} tabIndex={0} onClick={() => onOpen(r.model_key)} onKeyDown={(e) => { if (e.key === 'Enter') onOpen(r.model_key); }}>
            <td><b>{r.name}</b>
              <small className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                {r.source === 'registry' ? <Chip tone="navy" title={r.registry_link}>Registre UC</Chip> : <Chip tone="grey" title="Aucune référence de paquet : pas de rattachement au registre, aucun rapprochement par nom">Non associé UC</Chip>}
                {r.simulated.includes(true) && <Chip tone="amber">Simulé</Chip>}
                {r.synthetic && <Chip tone="amber">Synthétique</Chip>}
              </small>
              <small>{r.source === 'registry' ? r.registry_link : r.model_key}</small></td>
            <td>{useCaseFr(r.use_case)}</td>
            <td>{r.versions.length ? r.versions.map((x) => <Chip key={x} tone="blue">v{x}</Chip>) : '—'}</td>
            <td className="num">{r.stations.length || '—'}</td>
            <td className="num">{r.n_inferences.toLocaleString('fr-FR')}</td>
            <td className="num opt">{ms(r.latency_p95)}</td>
            <td><DriftChip status={r.drift.status} />{r.open_alerts > 0 && <small>{r.open_alerts} alerte(s) ouverte(s)</small>}</td>
            <td className="num opt">{r.source === 'registry' ? '—' : r.corrections}</td>
            <td className="opt"><button className="btn btn-ghost" style={{ height: 34 }} onClick={(e) => { e.stopPropagation(); onOpen(r.model_key); }}>Ouvrir</button></td>
          </tr>))}</tbody></table></div>}
        {filtered.length > PAGE && <div className="row" style={{ justifyContent: 'flex-end', gap: 8, alignItems: 'center' }}>
          <button className="btn btn-ghost" disabled={!page} onClick={() => setPage(page - 1)}>Précédent</button>
          <span className="muted">{page + 1} / {Math.ceil(filtered.length / PAGE)}</span>
          <button className="btn btn-ghost" disabled={(page + 1) * PAGE >= filtered.length} onClick={() => setPage(page + 1)}>Suivant</button>
        </div>}
      </section>
      {detail}
    </div>
  );
}
