import { useState } from 'react';
import { mlops, type MonitoringReport } from '../../api/mlops';
import { DriftBars, GroupedBars } from './charts';
import { Badge, grid, KV, LinkButton, Loading, Panel, Stat, Technical, Unavailable, useNav } from './common';
import { errText, useMonitoring, useStore } from './data';
import { translate } from './messages';
import { dateTime, pct } from './metrics';
import { useSelection } from './selection';

export default function Monitoring() {
  const { go } = useNav();
  const store = useStore();
  const { model, loading, error } = useSelection();
  const monitoring = useMonitoring(model?.id ?? null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');

  if (error) return <Unavailable tone="red">{error}</Unavailable>;
  if (loading || !model) return <Loading />;

  const report = monitoring.data;
  const live = report?.available ? report : null;
  const shown: MonitoringReport | null = live ?? report?.last_snapshot ?? null;
  const freshness = live
    ? <Badge tone="green">En direct · lu le {dateTime(live.read_at)}</Badge>
    : shown ? <Badge tone="amber">Instantané · lu le {dateTime(shown.read_at)}</Badge>
      : <Badge tone="grey">Indisponible</Badge>;

  const refresh = async () => {
    setBusy(true);
    try {
      const r = await mlops.monitoring(model.id, true);
      setNote(r.available ? 'Lecture en direct réussie.' : `Lecture en direct impossible : ${translate(r.reason ?? '')}`);
      store.invalidate(`monitoring:${model.id}`, 'overview');
    } catch (e) {
      setNote(`Échec : ${errText(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const drift = shown?.metrics?.drift ?? [];
  const alerts = drift.filter((d) => d.alert);
  const ref = shown?.accuracies.accuracy_reference;
  const shifted = shown?.accuracies.accuracy_drift;

  return (
    <>
      <Panel title={`Monitoring · ${model.display_name}`} sub={shown?.table ? `Table Delta ${shown.table}` : undefined}
        right={<div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>{freshness}<button className="btn btn-ghost" style={{ height: 38 }} disabled={busy} onClick={refresh}>Relire en direct</button></div>}>
        {monitoring.loading && <Loading />}
        {monitoring.error && <Unavailable tone="red">Monitoring indisponible : {monitoring.error}</Unavailable>}
        {report && !report.available && (
          <Unavailable>
            Lecture en direct indisponible : {translate(report.reason ?? '')}. Le SQL warehouse n'est jamais démarré automatiquement (maîtrise des crédits).
            {shown ? ' Les valeurs ci-dessous proviennent du dernier instantané enregistré.' : ' Aucun instantané antérieur.'}
          </Unavailable>
        )}
        {note && <span className="muted" style={{ fontSize: 14 }}>{note}</span>}
      </Panel>

      {shown?.metrics && (
        <>
          <div style={grid(200)}>
            <Stat label="Variables en dérive" value={`${alerts.length} / ${drift.length}`} tone={alerts.length ? 'red' : 'green'} hint="indice PSI au-dessus de son seuil" />
            <Stat label="Calculé le" value={dateTime(shown.metrics.window_end).split(' ')[0]} hint={dateTime(shown.metrics.window_end).split(' ')[1]} />
            <Stat label="Observations" value={shown.metrics.n_inferences} hint="télémétrie (référence + scénario)" />
            <Stat label="Version surveillée" value={`v${shown.metrics.model.version}`} hint={shown.metrics.model.registered_model.split('.').pop()} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 18, alignItems: 'start' }}>
            <Panel title="Indicateurs de dérive des données" sub="PSI par variable ; trait pointillé = seuil renvoyé par l'API">
              <DriftBars items={drift.map((d) => ({ feature: label(d.feature), value: d.value, threshold: d.threshold, alert: d.alert }))} />
              <span className="muted" style={{ fontSize: 13 }}>Une dérive des données (luminosité, netteté, distribution des scores) n'est pas une preuve de dérive de concept.</span>
            </Panel>
            <Panel title="Exactitude étiquetée sur la télémétrie" sub="Scénarios de référence et de dérive simulée (images synthétiques) — pas une mesure de production">
              {ref == null && shifted == null
                ? <Unavailable tone="grey">Non disponible dans ce rapport.</Unavailable>
                : <GroupedBars max={1} format={pct} groups={[{ label: 'Exactitude', bars: [
                    ...(ref != null ? [{ label: 'Référence', value: ref, color: 'var(--green)' }] : []),
                    ...(shifted != null ? [{ label: 'Sous dérive', value: shifted, color: 'var(--red)' }] : []),
                  ] }]} />}
            </Panel>
          </div>
        </>
      )}

      <div style={grid(280)}>
        <Panel title="Performance en production">
          <Unavailable tone="grey">Indisponible : aucune annotation de production n'est encore raccordée au monitoring.</Unavailable>
        </Panel>
        <Panel title="Accord avec les annotations humaines">
          <Unavailable tone="grey">À raccorder : les corrections des opérateurs sont dans le Core, pas encore dans le monitoring.</Unavailable>
        </Panel>
        <Panel title="Mesures hors ligne (validation, test)">
          <span className="muted" style={{ fontSize: 14 }}>Évaluées à l'entraînement, sur le dataset du modèle.</span>
          <LinkButton onClick={() => go('registry', model.id)}>Voir dans le Model Registry →</LinkButton>
        </Panel>
        <Panel title="Historique sur 14 jours">
          <Unavailable tone="grey">Indisponible : aucun job de monitoring quotidien. Aucune courbe n'est simulée.</Unavailable>
        </Panel>
      </div>

      {shown && (
        <Technical title="Données brutes du rapport">
          <KV k="table" v={shown.table} />
          <KV k="lu le" v={shown.read_at ?? '—'} />
          {drift.map((d) => <KV key={d.feature} k={`${d.feature} (${d.method})`} v={`${d.value} / seuil ${d.threshold}`} />)}
          {Object.entries(shown.accuracies).map(([k, v]) => <KV key={k} k={k} v={v ?? '—'} />)}
        </Technical>
      )}
    </>
  );
}

const LABELS: Record<string, string> = { brightness: 'Luminosité', blur: 'Netteté (variance)', anomaly_score: "Score d'anomalie" };
const label = (feature: string) => LABELS[feature] ?? feature;
