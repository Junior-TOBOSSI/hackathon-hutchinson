import { useMemo, useState, type ReactNode } from 'react';
import { monitoring, type Alert, type CatalogRow, type DataKind, type Measure, type PerfVersion, type Reference } from '../../../api/monitoring';
import { Loading, Unavailable } from '../common';
import { errText, useStore } from '../data';
import { Chip, Donut, SearchField, SelectField } from '../ui';
import { Bars, PairedBars, Series } from './charts';
import {
  day, DECISIONS, driftHelp, DriftChip, dt, ms, num, OriginChip, pct, reasonFr, shortKey, SourceLine, useAlerts, useCaseFr, useDrift,
  useHistory, useHuman, useInferences, useModelDetail, useMonParams, usePerformance, useSignals,
} from './shared';

const TABS: [string, string][] = [
  ['overview', 'Vue d’ensemble'], ['performance', 'Performances'], ['drift', 'Dérives'], ['inferences', 'Inférences'],
  ['human', 'Corrections humaines'], ['alerts', 'Alertes'], ['history', 'Historique'],
];

/* Détail d'un modèle surveillé : chaque onglet charge ses données à l'ouverture. */
export default function ModelDetail({ modelKey, kind, row, onClose }: { modelKey: string; kind: DataKind; row: CatalogRow | null; onClose: () => void }) {
  const nav = useMonParams();
  const tab = TABS.some(([id]) => id === nav.tab) ? nav.tab : 'overview';
  const detail = useModelDetail(modelKey, kind);
  const m: CatalogRow | null = detail.data ? { ...detail.data, references: detail.data.references.length } : row;
  return (
    <section className="card tf-panel">
      <div className="mon-detail-head">
        <div className="col" style={{ gap: 6, minWidth: 0 }}>
          <h2 className="h2">{m?.name ?? shortKey(modelKey)}</h2>
          <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            {m?.source === 'registry' ? <Chip tone="navy">Registre Unity Catalog</Chip> : <Chip tone="grey">Opérationnel · non associé à Unity Catalog</Chip>}
            <Chip tone="blue">{useCaseFr(m?.use_case)}</Chip>
            <OriginChip kind={kind} />
            {m && <DriftChip status={m.drift.status} />}
          </div>
          <span className="muted" style={{ fontSize: 12, overflowWrap: 'anywhere' }}>{m?.source === 'registry' ? m.registry_link : modelKey}</span>
        </div>
        <button className="btn btn-ghost" style={{ height: 34 }} onClick={onClose} aria-label="Fermer le détail">×</button>
      </div>
      <div className="tf-tabs" role="tablist">
        {TABS.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => nav.set({ tab: id })}>{label}</button>)}
      </div>
      {detail.error && !m && <Unavailable tone="red">Modèle indisponible : {detail.error}</Unavailable>}
      {!m && detail.loading && <Loading />}
      {m && tab === 'overview' && <OverviewTab m={m} refs={detail.data?.references} alerts={detail.data?.alerts} loading={detail.loading} />}
      {m && tab === 'performance' && <PerformanceTab m={m} />}
      {m && tab === 'drift' && <DriftTab m={m} kind={kind} />}
      {m && tab === 'inferences' && <InferencesTab m={m} kind={kind} />}
      {m && tab === 'human' && <HumanTab m={m} kind={kind} />}
      {m && tab === 'alerts' && <AlertsTab m={m} />}
      {m && tab === 'history' && <HistoryTab m={m} kind={kind} />}
    </section>
  );
}

const NotAssociated = () => (
  <div className="mon-banner navy">
    Modèle opérationnel déclaré par les postes : aucune référence exacte de paquet (modèle Unity Catalog, version, SHA-256) n’accompagne ses inférences.
    Il n’est donc rapproché ni de quality_demo ni de quality_industrial (aucun rapprochement par nom).
  </div>
);
const NoProduction = () => <Unavailable tone="grey">Aucune inférence de production n’est associée à ce modèle du registre (traçabilité exacte des paquets attendue côté Edge).</Unavailable>;

function Kv({ items }: { items: [string, ReactNode][] }) {
  return <dl className="mon-kv">{items.map(([k, v]) => [<dt key={`${k}-k`}>{k}</dt>, <dd key={`${k}-v`}>{v}</dd>])}</dl>;
}

/* ------------------------------------------------------------------ 1. vue d'ensemble */

function OverviewTab({ m, refs, alerts, loading }: { m: CatalogRow; refs?: Reference[]; alerts?: Alert[]; loading: boolean }) {
  return (
    <div className="col" style={{ gap: 14 }}>
      {m.source === 'operational' ? <NotAssociated /> : <NoProduction />}
      <Kv items={[
        ['Clé de surveillance', <code>{m.model_key}</code>],
        ['Lien registre', m.source === 'registry' ? m.registry_link : 'non associé'],
        ['Versions observées', m.versions.length ? m.versions.map((v) => `v${v}`).join(', ') : '—'],
        ['Postes', m.stations.length ? m.stations.join(', ') : '—'],
        ['Inférences', m.n_inferences.toLocaleString('fr-FR')],
        ['Cycles / pièces inspectés', m.n_parts.toLocaleString('fr-FR')],
        ['Latence P95', ms(m.latency_p95)],
        ['Dernière activité', dt(m.last_activity)],
        ['Corrections humaines', m.source === 'registry' ? '—' : m.corrections],
        ['Surveillance statistique', <span className="row" style={{ gap: 6, flexWrap: 'wrap' }}><DriftChip status={m.drift.status} /><span className="muted">{driftHelp(m.drift.status)}</span></span>],
      ]} />
      {m.drift.reasons?.length ? <Unavailable>Raisons : {m.drift.reasons.map(reasonFr).join(' ; ')}</Unavailable> : null}
      <h3 style={{ margin: 0, fontSize: 17 }}>Références statistiques</h3>
      {loading && !refs ? <Loading /> : <RefTable refs={refs ?? []} />}
      <span className="muted" style={{ fontSize: 13 }}>{(alerts ?? []).filter((a) => a.state === 'open').length} alerte(s) ouverte(s) · {(alerts ?? []).length} au total</span>
    </div>
  );
}

function RefTable({ refs }: { refs: Reference[] }) {
  if (!refs.length) return <div className="mon-empty">Aucune référence figée : aucune dérive ne peut être évaluée pour ce modèle.</div>;
  return (
    <div className="tf-table-wrap"><table className="tf-table mon-table"><thead><tr><th>Référence</th><th>Source</th><th>Version</th><th className="num">Effectif</th><th>Représentativité</th><th>Figée le</th></tr></thead>
      <tbody>{refs.map((r) => (
        <tr key={r.reference_id} className="static">
          <td><code>{r.reference_id}</code>{r.window && <small>{dt(r.window.start)} → {dt(r.window.end)}</small>}</td>
          <td>{r.source === 'offline_test' ? 'Test hors ligne' : 'Fenêtre opérationnelle'}{r.synthetic ? <small>synthétique / simulée</small> : null}</td>
          <td>v{r.model_version}</td>
          <td className="num">{r.n}</td>
          <td>{r.representative ? <Chip tone="green">Représentative</Chip> : <Chip tone="amber" title={r.warnings.join(' ')}>Non représentative</Chip>}</td>
          <td>{dt(r.created_at)}</td>
        </tr>))}</tbody></table></div>
  );
}

/* ------------------------------------------------------------------ 2. performances */

const METRICS: [string, string, (v: number | null) => string][] = [
  ['accuracy', 'Accuracy', (v) => pct(v)], ['precision_nok', 'Précision NOK', (v) => pct(v)], ['recall_nok', 'Rappel NOK', (v) => pct(v)],
  ['f1_nok', 'F1-score NOK', (v) => pct(v)], ['false_rejects', 'Faux rejets', (v) => num(v, 0)], ['missed_defects', 'Défauts manqués', (v) => num(v, 0)],
  ['latency_ms_mean', 'Latence moyenne', ms], ['latency_ms_p95', 'Latence P95', ms],
];

function PerformanceTab({ m }: { m: CatalogRow }) {
  const perf = usePerformance(m.source === 'registry' ? m.model_id ?? null : null);
  const [version, setVersion] = useState('');
  if (m.source !== 'registry') return <><NotAssociated /><Unavailable tone="grey">Aucune évaluation hors ligne : ce modèle opérationnel n’est rattaché à aucune version du registre.</Unavailable></>;
  if (perf.loading) return <Loading what="Lecture des runs MLflow" />;
  if (perf.error) return <Unavailable tone="red">Performances indisponibles : {perf.error}</Unavailable>;
  const versions = perf.data?.versions ?? [];
  if (!versions.length) return <Unavailable tone="grey">Aucune version évaluée.</Unavailable>;
  const v = versions.find((x) => x.version === version) ?? versions[versions.length - 1];
  const group = perf.data?.comparable_groups.find((g) => g.includes(v.version)) ?? [v.version];
  const peers = versions.filter((x) => group.includes(x.version));
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="mon-banner navy">Évaluation hors ligne sur le split de test : ce ne sont pas des performances mesurées en production.</div>
      <div className="tf-filters"><SelectField label="Version" icon="none" value={v.version} onChange={setVersion}
        options={versions.map((x) => [x.version, `v${x.version}${x.aliases.length ? ` (${x.aliases.join(', ')})` : ''}${x.approved ? ' · approuvée' : ''}`])} /></div>
      <Kv items={[
        ['Dataset', `${v.dataset.id ?? 'inconnu'} · version ${v.dataset.version ?? 'inconnue'}`],
        ['Split', 'test'],
        ['Taille de l’échantillon', v.metrics.n_test != null ? `${num(v.metrics.n_test, 0)} images` : 'non renseignée par le run'],
        ['Représentativité', v.representative === false ? <Chip tone="amber">Non représentatif</Chip> : v.representative ? <Chip tone="green">Représentatif</Chip> : <Chip tone="grey">Inconnue</Chip>],
        ['Données', v.synthetic ? <Chip tone="amber">Synthétiques</Chip> : 'réelles'],
        ['Run MLflow', <code>{v.run_id}</code>],
      ]} />
      {v.warnings.length > 0 && <Unavailable>{v.warnings.map((w) => w.replace(/test of (\d+) images \(< (\d+)\): not representative/, 'test de $1 images (< $2) : non représentatif').replace('test size unknown: representativeness unknown', 'taille du test inconnue : représentativité inconnue')).join(' · ')}</Unavailable>}
      <div className="tf-metric-grid">
        {METRICS.map(([k, label, f]) => <div key={k} className="tf-box"><span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>{label}</span><b style={{ fontSize: 20 }}>{f(v.metrics[k] ?? null)}</b></div>)}
      </div>
      {v.per_class && <PerClass pc={v.per_class} />}
      {v.confusion && <Confusion c={v.confusion} />}
      <h3 style={{ margin: 0, fontSize: 17 }}>Comparaison des versions comparables</h3>
      <span className="muted" style={{ fontSize: 13 }}>Versions évaluées sur le même split de test (même empreinte) : {group.map((x) => `v${x}`).join(', ')}</span>
      <div className="tf-table-wrap"><table className="tf-table mon-table"><thead><tr><th>Version</th>{METRICS.slice(0, 6).map(([k, l]) => <th key={k} className="num">{l}</th>)}<th>Statut</th></tr></thead>
        <tbody>{peers.map((x: PerfVersion) => (
          <tr key={x.version} className={x.version === v.version ? 'selected static' : 'static'}><td>v{x.version}</td>
            {METRICS.slice(0, 6).map(([k, , f]) => <td key={k} className="num">{f(x.metrics[k] ?? null)}</td>)}
            <td>{x.approved ? <Chip tone="green">Approuvée</Chip> : <Chip tone="grey">Non approuvée</Chip>} {x.aliases.map((a) => <Chip key={a} tone="blue">{a}</Chip>)}</td></tr>))}
        </tbody></table></div>
    </div>
  );
}

function PerClass({ pc }: { pc: NonNullable<PerfVersion['per_class']> }) {
  return (
    <div className="tf-table-wrap"><table className="tf-table mon-table"><thead><tr><th>Classe</th><th className="num">Effectif</th><th className="num">Précision</th><th className="num">Rappel</th><th className="num">F1</th></tr></thead>
      <tbody>{Object.entries(pc).map(([c, r]) => <tr key={c} className="static"><td>{c}</td><td className="num">{r.support}</td><td className="num">{pct(r.precision)}</td><td className="num">{pct(r.recall)}</td><td className="num">{pct(r.f1)}</td></tr>)}</tbody>
    </table></div>
  );
}

function Confusion({ c }: { c: NonNullable<PerfVersion['confusion']> }) {
  const truths = Object.keys(c.matrix);
  const max = Math.max(1, ...truths.flatMap((t) => c.columns.map((p) => c.matrix[t][p] ?? 0)));
  return (
    <div className="col" style={{ gap: 6 }}>
      <span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>Matrice de confusion (lignes : vérité · colonnes : décision)</span>
      <div className="tf-table-wrap"><table className="tf-matrix"><thead><tr><th />{c.columns.map((p) => <th key={p}>{p}</th>)}</tr></thead>
        <tbody>{truths.map((t) => <tr key={t}><th style={{ textAlign: 'left' }}>{t}</th>{c.columns.map((p) => {
          const n = c.matrix[t][p] ?? 0;
          const ok = t === p;
          return <td key={p} style={{ background: n ? (ok ? `rgba(14,159,79,${0.15 + (0.6 * n) / max})` : `rgba(200,16,46,${0.12 + (0.5 * n) / max})`) : 'var(--surface-soft)', borderRadius: 8, fontWeight: 700 }}>{n}</td>;
        })}</tr>)}</tbody></table></div>
    </div>
  );
}

/* ------------------------------------------------------------------ 3. dérives */

const MEASURE_LABEL: Record<string, string> = { 'score/psi': 'PSI des scores', 'score/ks': 'KS des scores', 'decision_rate/psi': 'PSI des taux de décision', 'decision_rate/chi2': 'χ² des décisions', 'latency/mean_shift': 'Écart de latence moyenne' };

function DriftTab({ m, kind }: { m: CatalogRow; kind: DataKind }) {
  const store = useStore();
  const detail = useModelDetail(m.model_key, kind);
  const alerts = useAlerts();
  const [version, setVersion] = useState(m.drift.version ?? m.versions[m.versions.length - 1] ?? '');
  const [population, setPopulation] = useState<DataKind>(kind);
  const [refId, setRefId] = useState('');
  const refs = (detail.data?.references ?? []).filter((r) => r.model_version === version);
  const drift = useDrift(m.source === 'operational' && version ? { model_key: m.model_key, version, data_kind: population, reference_id: refId || undefined } : null);
  const d = drift.data;
  const ref = refs.find((r) => r.reference_id === (d?.reference_id ?? refId));
  const history = (alerts.data ?? []).filter((a) => a.kind === 'drift' && a.model_key === m.model_key);

  if (m.source === 'registry') {
    return (
      <div className="col" style={{ gap: 14 }}>
        <NoProduction />
        <span className="muted" style={{ fontSize: 14 }}>Les références hors ligne de ce modèle restent consultables ; elles ne seront comparées qu’à des inférences rattachées exactement à cette version.</span>
        {detail.loading ? <Loading /> : <RefTable refs={detail.data?.references ?? []} />}
      </div>
    );
  }
  const labels = (d?.histogram?.edges ?? []).slice(0, -1).map((e, i, all) => {
    const hi = d?.histogram?.edges[i + 1];
    return i === 0 ? `≤ ${num(hi ?? null, 2)}` : i === all.length - 1 ? `> ${num(e, 2)}` : `${num(e, 2)}–${num(hi ?? null, 2)}`;
  });
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="tf-filters">
        <SelectField label="Version" icon="none" value={version} onChange={(v) => { setVersion(v); setRefId(''); }} options={m.versions.map((v) => [v, `v${v}`])} />
        <SelectField label="Population surveillée" icon="none" value={population} onChange={(v) => setPopulation(v as DataKind)} options={[['real', 'Production réelle'], ['simulated', 'Données simulées']]} />
        <SelectField label="Référence" allLabel="Dernière référence de la version" value={refId} onChange={setRefId} options={refs.map((r) => [r.reference_id, `${r.reference_id} · n=${r.n}${r.representative ? '' : ' · non représentative'}`])} />
      </div>
      {drift.loading && <Loading what="Calcul de la dérive" />}
      {drift.error && <Unavailable tone="red">Dérive indisponible : {drift.error}</Unavailable>}
      {d && (
        <>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <DriftChip status={d.status} /><span className="muted" style={{ fontSize: 14 }}>{driftHelp(d.status)}</span>
          </div>
          {d.status === 'reference_absent' && <div className="mon-empty">Aucune référence figée pour v{version}. Figez une fenêtre opérationnelle compatible ci-dessous (aucune alerte n’est possible sans référence).</div>}
          {d.reasons?.length ? <Unavailable tone="red">Comparaison refusée : {d.reasons.map(reasonFr).join(' ; ')}</Unavailable> : null}
          {d.reference_id && <Kv items={[
            ['Référence', <code>{d.reference_id}</code>],
            ['Source', ref?.source === 'offline_test' ? 'Test hors ligne' : ref?.source === 'operational_window' ? `Fenêtre opérationnelle ${ref.window ? `${dt(ref.window.start)} → ${dt(ref.window.end)}` : ''}` : d.reference_source ?? '—'],
            ['Représentativité', d.reference_representative ? <Chip tone="green">Représentative</Chip> : <Chip tone="amber">Non représentative</Chip>],
            ['Effectifs', `référence ${d.n_reference ?? '—'} · population ${d.n_current ?? '—'} (minimum ${d.thresholds?.min_reference ?? '—'} / ${d.thresholds?.min_current ?? '—'})`],
            ['Seuils (backend)', d.thresholds ? `PSI ${num(d.thresholds.psi_watch, 2)} surveillance · ${num(d.thresholds.psi_alert, 2)} alerte · latence +${Math.round(d.thresholds.latency_shift_ratio * 100)} %` : '—'],
          ]} />}
          {d.reference_warnings?.length ? <Unavailable>{d.reference_warnings.map((w) => w.replace(/only (\d+) observations \(< (\d+)\): not representative, no reliable alert/, 'seulement $1 observations (< $2) : non représentative, aucune alerte fiable')).join(' · ')}</Unavailable> : null}
          {d.histogram && <PairedBars labels={labels} reference={d.histogram.reference} current={d.histogram.current} />}
          {d.measures && <div className="tf-table-wrap"><table className="tf-table mon-table"><thead><tr><th>Indicateur</th><th className="num">Valeur</th><th className="num">p-valeur</th><th className="num">Seuil</th><th>Niveau</th></tr></thead>
            <tbody>{d.measures.map((x: Measure) => (
              <tr key={`${x.indicator}/${x.method}`} className="static"><td>{MEASURE_LABEL[`${x.indicator}/${x.method}`] ?? `${x.indicator} ${x.method}`}{x.method_detail && <small>{x.method_detail}</small>}{x.applicable === false && <small>non applicable : {x.reason === 'expected count < 5' ? 'effectif attendu < 5' : x.reason === 'empty category' ? 'catégorie vide' : x.reason}</small>}</td>
                <td className="num">{x.method === 'mean_shift' ? pct(x.value ?? null) : num(x.value ?? x.statistic ?? null)}</td>
                <td className="num">{x.p_value != null ? num(x.p_value, 4) : '—'}</td>
                <td className="num">{x.threshold != null ? (x.method === 'mean_shift' ? `+${pct(x.threshold, 0)}` : num(x.threshold, 2)) : '—'}</td>
                <td>{x.level ? <DriftChip status={x.level === 'unavailable' ? 'insufficient_current' : x.level} /> : '—'}</td></tr>))}</tbody></table></div>}
          {d.note && <span className="muted" style={{ fontSize: 13 }}>Dérive des données et des scores uniquement : ce n’est pas une preuve de dérive de concept.</span>}
        </>
      )}
      <FreezeReference m={m} version={version} kind={population} onDone={() => store.invalidate(`mon:model:${m.model_key}`, 'mon:drift:', 'mon:models:')} />
      <h3 style={{ margin: 0, fontSize: 17 }}>Historique des dérives</h3>
      {history.length ? <AlertTable alerts={history} /> : <div className="mon-empty">Aucune alerte de dérive enregistrée pour ce modèle (les alertes ne sont évaluées qu’à la collecte explicite, contre une référence suffisante).</div>}
      <span className="muted" style={{ fontSize: 13 }}>Consulter une dérive ne déclenche jamais de réentraînement.</span>
    </div>
  );
}

function FreezeReference({ m, version, kind, onDone }: { m: CatalogRow; version: string; kind: DataKind; onDone: () => void }) {
  const inf = useInferences({ data_kind: kind, model_key: m.model_key, version });
  const t = inf.data?.total;
  const toLocal = (iso: string | null | undefined) => (iso ? new Date(new Date(iso).getTime() - new Date(iso).getTimezoneOffset() * 60_000).toISOString().slice(0, 16) : '');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [msg, setMsg] = useState<{ tone: 'red' | 'amber' | 'grey'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const s = start || toLocal(t?.first_activity);
  const e = end || (t?.last_activity ? toLocal(new Date(new Date(t.last_activity).getTime() + 60_000).toISOString()) : '');
  const submit = async () => {
    if (!s || !e || !version) return;
    const body = { source: 'operational_window' as const, model_key: m.model_key, version, data_kind: kind, start: new Date(s).toISOString(), end: new Date(e).toISOString() };
    if (!window.confirm(`Figer une référence IMMUABLE pour ${shortKey(m.model_key)} v${version} ?\n\nOrigine : ${kind === 'real' ? 'production réelle' : 'données simulées'}\nFenêtre : ${dt(body.start)} → ${dt(body.end)}\n\nÉcriture locale uniquement ; une référence identique sera refusée par le backend.`)) return;
    setBusy(true);
    try {
      const r = await monitoring.freeze(body);
      setMsg({ tone: r.representative ? 'grey' : 'amber', text: `Référence ${r.reference_id} figée : ${r.n} observation(s)${r.representative ? '.' : ' — non représentative, aucune alerte fiable.'}` });
      onDone();
    } catch (err) {
      setMsg({ tone: 'red', text: `Refusé par le backend : ${errText(err)}` });
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="tf-box">
      <summary style={{ cursor: 'pointer', fontWeight: 700 }}>Figer une référence opérationnelle</summary>
      <span className="muted" style={{ fontSize: 13 }}>Fenêtre d’inférences de v{version || '—'} ({kind === 'real' ? 'production réelle' : 'données simulées'}, jamais les deux). La référence est immuable ; le backend valide la demande.</span>
      <div className="mon-form">
        <label>Début<input type="datetime-local" value={s} onChange={(x) => setStart(x.target.value)} /></label>
        <label>Fin (exclue)<input type="datetime-local" value={e} onChange={(x) => setEnd(x.target.value)} /></label>
        <button className="btn btn-primary" disabled={busy || !s || !e || !version} onClick={submit}>Figer la référence…</button>
      </div>
      {msg && <Unavailable tone={msg.tone}>{msg.text}</Unavailable>}
    </details>
  );
}

/* ------------------------------------------------------------------ 4. inférences */

function InferencesTab({ m, kind }: { m: CatalogRow; kind: DataKind }) {
  const [version, setVersion] = useState('');
  const inf = useInferences(m.source === 'operational' ? { data_kind: kind, model_key: m.model_key, version: version || undefined } : null);
  if (m.source === 'registry') return <NoProduction />;
  if (inf.loading) return <Loading />;
  if (inf.error || !inf.data) return <Unavailable tone="red">Inférences indisponibles : {inf.error}</Unavailable>;
  const o = inf.data;
  const t = o.total;
  const edges = t.score_histogram.edges;
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="row between" style={{ gap: 10, flexWrap: 'wrap' }}>
        <SelectField label="Version" allLabel="Toutes les versions" value={version} onChange={setVersion} options={m.versions.map((v) => [v, `v${v}`])} />
        <SourceLine sources={o.sources} res={inf} />
      </div>
      {o.status === 'partial' && <div className="mon-banner">Agrégation partielle : lecture Core tronquée (500 éléments par poste).</div>}
      <div className="tf-metric-grid">
        {([['Inférences', t.n_inferences.toLocaleString('fr-FR')], ['Cycles / pièces inspectés', t.n_parts.toLocaleString('fr-FR')],
          ['Cadence', t.cadence_per_hour != null ? `${num(t.cadence_per_hour, 1)} / h` : '—'], ['Latence moyenne', ms(t.latency_ms.mean)],
          ['Latence P50', ms(t.latency_ms.p50)], ['Latence P95', ms(t.latency_ms.p95)], ['Score moyen', num(t.score_mean)], ['Dernière activité', dt(t.last_activity)]] as [string, string][])
          .map(([l, v]) => <div key={l} className="tf-box"><span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>{l}</span><b style={{ fontSize: 19 }}>{v}</b></div>)}
      </div>
      <span className="muted" style={{ fontSize: 13 }}>
        Inférences = événements d’inférence dédupliqués ; cycles = cycles distincts ayant reçu une inférence. Pièces produites (API Core) : {o.parts.n_parts}
        {o.parts.with_inference_error ? `, dont ${o.parts.with_inference_error} en erreur (${Object.entries(o.parts.error_codes).map(([c, n]) => `${c} ${n}`).join(', ')})` : ''}.
      </span>
      <div className="mon-charts">
        <section className="mon-card tf-box"><h3>Distribution des scores</h3>
          <Bars counts={t.score_histogram.counts} labels={edges.slice(0, -1).map((e) => num(e, 2))} caption="20 classes de largeur 0,05 sur [0 ; 1]" /></section>
        <section className="mon-card tf-box"><h3>Taux de décisions</h3>
          <Donut centerLabel="inférences" items={DECISIONS.map((d) => ({ label: d.label, count: t.decision_counts[d.id] ?? 0, color: d.color }))} /></section>
      </div>
      <h3 style={{ margin: 0, fontSize: 17 }}>Ventilation par poste et version effectivement utilisée</h3>
      <div className="tf-table-wrap"><table className="tf-table mon-table"><thead><tr><th>Poste</th><th>Version</th><th className="num">Inférences</th><th className="num">OK</th><th className="num">NOK</th><th className="num">À vérifier</th><th className="num">P95</th><th>Dernière activité</th></tr></thead>
        <tbody>{o.groups.map((g) => (
          <tr key={`${g.station_id}-${g.model_version}`} className="static"><td>{g.station_id}</td><td>v{g.model_version}</td><td className="num">{g.n_inferences}</td>
            <td className="num">{g.decision_counts.conforme}</td><td className="num">{g.decision_counts.anomalie}</td><td className="num">{g.decision_counts.a_verifier}</td>
            <td className="num">{ms(g.latency_ms.p95)}</td><td>{dt(g.last_activity)}</td></tr>))}</tbody></table></div>
    </div>
  );
}

/* ------------------------------------------------------------------ 5. corrections humaines */

function HumanTab({ m, kind }: { m: CatalogRow; kind: DataKind }) {
  const h = useHuman(m.source === 'operational' ? { data_kind: kind, model_key: m.model_key } : null);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const items = useMemo(() => (h.data?.items ?? []).filter((c) => `${c.station_id} ${c.part_id} ${c.reason ?? ''} ${c.new_verdict} ${c.ai_initial ?? ''}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())), [h.data, query]);
  if (m.source === 'registry') return <NoProduction />;
  if (h.loading) return <Loading />;
  if (h.error || !h.data) return <Unavailable tone="red">Corrections indisponibles : {h.error}</Unavailable>;
  const d = h.data;
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="tf-metric-grid">
        {([['Pièces corrigées', d.corrected_parts], ['Corrections', d.corrections], ['Faux rejets observés', d.false_rejects_observed],
          ['Défauts manqués observés', d.missed_defects_observed], ['Inspections physiques', d.physical_inspections], ['Taux d’accord humain', 'Indisponible']] as [string, string | number][])
          .map(([l, v]) => <div key={l} className="tf-box"><span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>{l}</span><b style={{ fontSize: 19 }}>{v}</b></div>)}
      </div>
      <Unavailable>
        Taux d’accord indisponible : le Core n’enregistre que les corrections, pas les confirmations sans correction ; le nombre de pièces vérifiées est inconnu.
        Une pièce non corrigée n’est pas une prédiction confirmée, et ces désaccords observés ne sont pas une précision de production.
      </Unavailable>
      <SearchField placeholder="Rechercher (poste, pièce, motif…)" value={query} onChange={(x) => { setQuery(x); setPage(0); }} />
      {items.length === 0 ? <div className="mon-empty">Aucune correction pour ces critères.</div> : (
        <div className="tf-table-wrap"><table className="tf-table mon-table"><thead><tr><th>Date</th><th>Poste</th><th>Modèle · version</th><th>Verdict IA initial</th><th>Verdict corrigé</th><th>Motif</th><th>Inspection</th></tr></thead>
          <tbody>{items.slice(page * 10, page * 10 + 10).map((c) => (
            <tr key={c.correction_id} className="static"><td>{dt(c.at)}<small>correction n°{c.sequence}</small></td><td>{c.station_id}</td>
              <td>{c.model_key ? shortKey(c.model_key) : 'non relié'}{c.model_version && <small>v{c.model_version}</small>}</td>
              <td>{c.ai_initial ?? '—'}{c.previous_verdict && c.previous_verdict !== c.ai_initial && <small>avant correction : {c.previous_verdict}</small>}</td>
              <td><b>{c.new_verdict}</b></td><td>{c.reason ?? '—'}</td><td>{c.physical_inspection ? <Chip tone="green">Physique</Chip> : <Chip tone="grey">Non</Chip>}</td></tr>))}</tbody></table></div>
      )}
      {items.length > 10 && <div className="row" style={{ justifyContent: 'flex-end', gap: 8, alignItems: 'center' }}>
        <button className="btn btn-ghost" disabled={!page} onClick={() => setPage(page - 1)}>Précédent</button>
        <span className="muted">{page + 1} / {Math.ceil(items.length / 10)}</span>
        <button className="btn btn-ghost" disabled={(page + 1) * 10 >= items.length} onClick={() => setPage(page + 1)}>Suivant</button></div>}
    </div>
  );
}

/* ------------------------------------------------------------------ 6. alertes */

const SIGNALS: Record<string, string> = {
  persistent_drift: 'Dérive persistante', new_validated_annotations: 'Nouvelles annotations validées', performance_degradation: 'Dégradation de performance',
  schedule: 'Calendrier', manual_request: 'Demande manuelle',
};

function AlertTable({ alerts }: { alerts: Alert[] }) {
  return (
    <div className="tf-table-wrap"><table className="tf-table mon-table"><thead><tr><th>Type</th><th>Indicateur</th><th className="num">Valeur</th><th className="num">Seuil</th><th className="num">Effectif</th><th>Référence</th><th>Périmètre</th><th>État</th></tr></thead>
      <tbody>{alerts.map((a) => (
        <tr key={a.alert_key} className="static"><td>{a.kind === 'drift' ? 'Dérive' : 'Disponibilité'}</td><td>{a.indicator}{a.method && <small>{a.method}</small>}</td>
          <td className="num">{typeof a.value === 'number' ? num(a.value) : a.value ?? '—'}</td><td className="num">{a.threshold != null ? num(a.threshold, 2) : '—'}</td>
          <td className="num">{a.n ?? '—'}</td><td>{a.reference_id ? <code>{a.reference_id}</code> : '—'}</td>
          <td>{a.station_id ?? a.scope ?? '—'}{a.model_version && <small>v{a.model_version} · {a.data_kind === 'simulated' ? 'simulé' : a.data_kind === 'real' ? 'réel' : ''}</small>}</td>
          <td>{a.state === 'open' ? <Chip tone="red">Ouverte</Chip> : <Chip tone="green">Résolue</Chip>}<small>depuis {dt(a.first_detected)} · vue {dt(a.last_detected)}{a.resolved_at ? ` · résolue ${dt(a.resolved_at)}` : ''}</small></td></tr>))}</tbody></table></div>
  );
}

function AlertsTab({ m }: { m: CatalogRow }) {
  const alerts = useAlerts();
  const signals = useSignals(m.source === 'registry' ? m.model_id ?? null : null);
  const mine = (alerts.data ?? []).filter((a) => a.model_key === m.model_key);
  return (
    <div className="col" style={{ gap: 14 }}>
      {alerts.loading ? <Loading /> : alerts.error ? <Unavailable tone="red">Alertes indisponibles : {alerts.error}</Unavailable>
        : mine.length ? <AlertTable alerts={mine} /> : <div className="mon-empty">Aucune alerte persistée pour ce modèle. {m.drift.status === 'reference_absent' ? 'Sans référence, aucune dérive ne peut être détectée.' : m.drift.status.startsWith('insufficient') ? 'Les effectifs sont insuffisants pour une alerte fiable.' : ''}</div>}
      <span className="muted" style={{ fontSize: 13 }}>Les alertes sont évaluées uniquement lors d’une collecte explicite (bouton « Collecter maintenant ») ; l’ouverture de la page n’écrit rien.</span>
      <h3 style={{ margin: 0, fontSize: 17 }}>Signaux de réentraînement (lecture seule)</h3>
      {m.source !== 'registry' ? <Unavailable tone="grey">Signaux disponibles pour les modèles du registre uniquement.</Unavailable>
        : signals.loading ? <Loading /> : signals.error ? <Unavailable tone="red">Signaux indisponibles : {signals.error}</Unavailable> : signals.data && (
          <>
            <div className="row" style={{ gap: 8 }}>{signals.data.eligible ? <Chip tone="amber">Conditions réunies</Chip> : <Chip tone="grey">Non éligible</Chip>}
              <span className="muted" style={{ fontSize: 13 }}>Aucune action : l’approbation et le déploiement restent des décisions humaines (planification : DBX-08).</span></div>
            <div className="tf-table-wrap"><table className="tf-table mon-table"><thead><tr><th>Condition</th><th>Remplie</th><th>Détail</th></tr></thead>
              <tbody>{Object.entries(signals.data.conditions).map(([k, c]) => (
                <tr key={k} className="static"><td>{SIGNALS[k] ?? k}</td><td>{c.met ? <Chip tone="amber">Oui</Chip> : <Chip tone="grey">Non</Chip>}</td>
                  <td style={{ fontSize: 12 }}>{Object.entries(c).filter(([x]) => x !== 'met').map(([x, v]) => `${x} : ${v ?? '—'}`).join(' · ')}</td></tr>))}</tbody></table></div>
          </>
        )}
    </div>
  );
}

/* ------------------------------------------------------------------ 7. historique */

function HistoryTab({ m, kind }: { m: CatalogRow; kind: DataKind }) {
  const hist = useHistory(kind);
  if (m.source === 'registry') return <NoProduction />;
  if (hist.loading) return <Loading />;
  if (hist.error || !hist.data) return <Unavailable tone="red">Historique indisponible : {hist.error}</Unavailable>;
  const snaps = hist.data.snapshots.filter((s) => s.scope_key.startsWith(`${m.model_key}|`));
  const versions = Array.from(new Set(snaps.map((s) => s.scope_key.split('|')[1])));
  return (
    <div className="col" style={{ gap: 14 }}>
      {snaps.length === 0 ? <div className="mon-empty">Aucun instantané collecté pour ce modèle ({kind === 'real' ? 'production réelle' : 'données simulées'}). L’historique se construit uniquement par collecte explicite.</div> : (
        <>
          {versions.map((v) => {
            const rows = snaps.filter((s) => s.scope_key.split('|')[1] === v);
            return (
              <div key={v} className="mon-charts">
                <section className="mon-card tf-box"><h3>Volume · v{v}</h3>
                  <Series points={rows.map((s) => ({ x: day(s.window_start), values: { Inférences: s.n_inferences } }))} series={[{ name: 'Inférences', color: 'var(--primary)' }]} format={(n) => String(n)} empty="—" /></section>
                <section className="mon-card tf-box"><h3>Latences · v{v}</h3>
                  <Series points={rows.map((s) => ({ x: day(s.window_start), values: { P50: s.latency_ms.p50, P95: s.latency_ms.p95 } }))} series={[{ name: 'P50', color: 'var(--primary-light)' }, { name: 'P95', color: 'var(--red)' }]} format={ms} empty="—" /></section>
              </div>
            );
          })}
          <div className="tf-table-wrap"><table className="tf-table mon-table"><thead><tr><th>Jour</th><th>Version</th><th className="num">Inférences</th><th className="num">OK</th><th className="num">NOK</th><th className="num">À vérifier</th><th className="num">P50</th><th className="num">P95</th><th>Calculé le</th></tr></thead>
            <tbody>{snaps.map((s) => (
              <tr key={s.snapshot_id} className="static"><td>{day(s.window_start)}{s.partial && <small>partiel</small>}</td><td>v{s.scope_key.split('|')[1]}</td><td className="num">{s.n_inferences}</td>
                <td className="num">{s.decision_counts.conforme}</td><td className="num">{s.decision_counts.anomalie}</td><td className="num">{s.decision_counts.a_verifier}</td>
                <td className="num">{ms(s.latency_ms.p50)}</td><td className="num">{ms(s.latency_ms.p95)}</td><td>{dt(s.computed_at)}</td></tr>))}</tbody></table></div>
        </>
      )}
      <h3 style={{ margin: 0, fontSize: 17 }}>Journal des collectes</h3>
      {hist.data.collections.length ? (
        <div className="tf-table-wrap"><table className="tf-table mon-table"><thead><tr><th>Date</th><th className="num">Instantanés</th><th className="num">Alertes ouvertes</th><th className="num">Résolues</th><th>Données</th></tr></thead>
          <tbody>{hist.data.collections.map((c) => (
            <tr key={c.collection_id} className="static"><td>{dt(c.at)}</td><td className="num">{c.snapshots_written}</td><td className="num">{c.open_alerts}</td><td className="num">{c.resolved_alerts}</td><td>{c.partial ? <Chip tone="amber">Partielles</Chip> : <Chip tone="green">Complètes</Chip>}</td></tr>))}</tbody></table></div>
      ) : <div className="mon-empty">Aucune collecte enregistrée.</div>}
    </div>
  );
}
