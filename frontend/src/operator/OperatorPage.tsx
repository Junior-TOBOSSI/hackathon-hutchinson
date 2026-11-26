import { useCurrentShift, useParts } from "../api/hooks";
import { config } from "../app/config";
import { Card, QueryState, StatTile, VerdictBadge, percent } from "../shared/components";

/** SKELETON — Operator space (talks to the local Edge API only). Owned by ARGOS Frontend. */
export function OperatorPage() {
  const shift = useCurrentShift(config.stationId);
  const parts = useParts(config.stationId);
  const kpi = shift.data?.kpi;

  return (
    <div className="grid gap-4">
      <h1 className="text-xl font-semibold">Poste {config.stationId}</h1>
      <Card title="Shift en cours">
        <QueryState isLoading={shift.isLoading} error={shift.error} />
        {kpi && (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
            <StatTile label="OK" value={kpi.ok_parts} tone="text-verdict-ok" />
            <StatTile label="NOK" value={kpi.nok_parts} tone="text-verdict-nok" />
            <StatTile label="À vérifier" value={kpi.hold_parts} tone="text-verdict-hold" />
            <StatTile label="Erreur" value={kpi.error_parts} tone="text-verdict-error" />
            <StatTile label="Objectif" value={`${kpi.ok_parts} / ${kpi.target_parts ?? "—"}`} />
            <StatTile label="Taux NOK" value={percent(kpi.nok_rate)} />
          </div>
        )}
      </Card>
      <Card title="Dernières pièces">
        <QueryState isLoading={parts.isLoading} error={parts.error} />
        <table className="w-full text-left text-sm">
          <thead className="text-slate-400">
            <tr>
              <th>Cycle</th>
              <th>Prédiction IA</th>
              <th>Verdict effectif</th>
              <th>Corrections</th>
            </tr>
          </thead>
          <tbody>
            {parts.data?.map((p) => (
              <tr key={p.part_id} className="border-t border-argos-line">
                <td className="py-1 font-mono">{p.cycle_id}</td>
                <td>
                  <VerdictBadge verdict={p.predicted_verdict} />
                </td>
                <td>
                  <VerdictBadge verdict={p.effective_verdict} />
                </td>
                <td>{p.correction_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
