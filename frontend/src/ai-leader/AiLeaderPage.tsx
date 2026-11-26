import { useDeployments, useModels, useMonitoring } from "../api/hooks";
import { Card, QueryState } from "../shared/components";

/** SKELETON — AI Leader space (talks to ARGOS Core, which mirrors MLflow). Owned by ARGOS Frontend. */
export function AiLeaderPage() {
  const models = useModels();
  const deployments = useDeployments();
  const monitoring = useMonitoring();

  return (
    <div className="grid gap-4">
      <h1 className="text-xl font-semibold">Cycle de vie des modèles</h1>
      <Card title="Modèles (MLflow Registry)">
        <QueryState isLoading={models.isLoading} error={models.error} />
        <ul className="text-sm">
          {models.data?.map((m) => (
            <li key={`${m.model.registered_model}-${m.model.version}`} className="border-t border-argos-line py-1">
              {m.use_case} · {m.model.registered_model} v{m.model.version}
              {m.model.alias ? ` (@${m.model.alias})` : ""} · {m.runtime}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Déploiements">
        <QueryState isLoading={deployments.isLoading} error={deployments.error} />
        <ul className="text-sm">
          {deployments.data?.map((d) => (
            <li key={d.deployment_id} className="border-t border-argos-line py-1">
              {d.station_id} · {d.use_case} v{d.model.version} → {d.status}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Dérives">
        <QueryState isLoading={monitoring.isLoading} error={monitoring.error} />
        <ul className="text-sm">
          {monitoring.data?.flatMap((m) =>
            (m.drift ?? []).map((d) => (
              <li key={`${m.use_case}-${d.feature}`} className={d.alert ? "text-verdict-nok" : ""}>
                {m.use_case} · {d.feature} ({d.method}) = {d.value} / seuil {d.threshold}
              </li>
            )),
          )}
        </ul>
      </Card>
    </div>
  );
}
