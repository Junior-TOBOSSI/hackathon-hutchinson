import { useMemo } from "react";

import { useAlerts, useStations } from "../api/hooks";
import { Card, QueryState, SimulatedBadge } from "../shared/components";
import { PlotlyChart } from "../shared/PlotlyChart";

/** SKELETON — Supervisor space (talks to ARGOS Core). Owned by ARGOS Frontend. */
export function SupervisorPage() {
  const stations = useStations();
  const alerts = useAlerts();

  const chart = useMemo(() => {
    const rows = stations.data ?? [];
    const ids = rows.map((s) => s.station_id);
    const value = (key: "ok_parts" | "nok_parts") => rows.map((s) => s.current_shift?.kpi[key] ?? 0);
    return [
      { type: "bar", name: "OK", x: ids, y: value("ok_parts"), marker: { color: "#22c55e" } },
      { type: "bar", name: "NOK", x: ids, y: value("nok_parts"), marker: { color: "#ef4444" } },
    ];
  }, [stations.data]);

  return (
    <div className="grid gap-4">
      <h1 className="text-xl font-semibold">Supervision multiposte</h1>
      <Card title="Postes">
        <QueryState isLoading={stations.isLoading} error={stations.error} />
        <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
          {stations.data?.map((s) => (
            <div key={s.station_id} className="rounded border border-argos-line p-2 text-sm">
              <div className="flex items-center justify-between font-semibold">
                {s.station_id} {s.simulated && <SimulatedBadge />}
              </div>
              <div className={s.online ? "text-verdict-ok" : "text-verdict-nok"}>
                {s.online ? "en ligne" : "hors ligne"}
              </div>
              <div className="text-xs text-slate-400">{s.open_alerts} alerte(s)</div>
            </div>
          ))}
        </div>
      </Card>
      <Card title="Production du shift par poste">
        <PlotlyChart data={chart} layout={{ barmode: "stack" }} />
      </Card>
      <Card title="Alertes">
        <QueryState isLoading={alerts.isLoading} error={alerts.error} />
        <ul className="text-sm">
          {alerts.data?.map((a) => (
            <li key={a.alert_id} className="border-t border-argos-line py-1">
              [{a.severity}] {a.station_id} — {a.title} ({a.status}, ×{a.occurrences})
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
