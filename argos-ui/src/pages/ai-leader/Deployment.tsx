import { Badge, grid, KV, LinkButton, Loading, Panel, Technical, Unavailable, useNav } from './common';
import { useEndpoints, useStatuses } from './data';
import { useSelection, versionRoles } from './selection';

/** Ce que Model Serving exécute réellement. Consultation seule : le changement de
   version servie et le rollback seront raccordés dans un chantier ultérieur. */
export default function Deployment() {
  const { go } = useNav();
  const endpoints = useEndpoints();
  const { models } = useSelection();
  const statuses = useStatuses().data ?? [];

  return (
    <>
      <Panel title="Deployment Center" sub="Endpoints Model Serving personnalisés (les endpoints de modèles de fondation Databricks ne sont pas listés)">
        <Unavailable tone="grey">Changement de version servie et rollback : non disponibles dans HOVIS à ce stade (chantier suivant). Aucune action de déploiement n'est proposée ici.</Unavailable>
      </Panel>
      {endpoints.error && <Unavailable tone="red">Serving indisponible : {endpoints.error}</Unavailable>}
      {endpoints.loading && <Loading />}
      {endpoints.data?.length === 0 && <Unavailable tone="grey">Aucun endpoint personnalisé.</Unavailable>}
      <div style={grid(420)}>
        {endpoints.data?.map((e) => (
          <section key={e.name} className="card col" style={{ gap: 14 }}>
            <div className="between" style={{ flexWrap: 'wrap' }}>
              <span className="h2" style={{ fontSize: 22 }}>{e.name}</span>
              <Badge tone={e.ready === 'READY' ? 'green' : 'red'}>{e.ready === 'READY' ? 'prêt' : e.ready ?? 'inconnu'}</Badge>
            </div>
            {e.served.map((s) => {
              const managed = models.find((m) => m.uc_name === s.model);
              const roles = versionRoles(statuses.find((x) => x.model_id === managed?.id) ?? null);
              return (
                <div key={s.name ?? s.model ?? ''} className="col" style={{ gap: 10 }}>
                  <div style={grid(150)}>
                    <Fact label="Modèle servi" value={managed?.display_name ?? s.model ?? '—'} />
                    <Fact label="Version servie" value={s.version ? `v${s.version}` : '—'} big />
                    <Fact label="Calcul" value={`CPU · ${s.workload_size ?? '—'}`} />
                    <Fact label="Scale to zero" value={s.scale_to_zero ? 'activé' : 'désactivé'} />
                  </div>
                  <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                    <Badge tone={s.deployment === 'DEPLOYMENT_READY' ? 'green' : 'amber'}>{s.deployment === 'DEPLOYMENT_READY' ? 'déploiement prêt' : s.deployment ?? 'état inconnu'}</Badge>
                    {roles.champion && <Badge tone={roles.champion === s.version ? 'blue' : 'amber'}>{roles.champion === s.version ? 'sert le champion' : `champion = v${roles.champion}, non servi`}</Badge>}
                    {s.version && roles.approved.includes(s.version) ? <Badge tone="green">version approuvée</Badge> : s.version ? <Badge tone="amber">version non approuvée</Badge> : null}
                  </div>
                  {managed && <div className="row" style={{ gap: 14, fontSize: 14 }}><LinkButton onClick={() => go('registry', managed.id)}>Voir les versions</LinkButton><LinkButton onClick={() => go('monitoring', managed.id)}>Voir le monitoring</LinkButton></div>}
                </div>
              );
            })}
            {e.pending_versions.length > 0 && <Unavailable>Mise à jour en cours vers v{e.pending_versions.join(', v')}.</Unavailable>}
            <Technical>
              <KV k="config_update" v={e.config_update ?? '—'} />
              {e.served.map((s) => <KV key={s.name ?? ''} k={`entité ${s.name}`} v={`${s.model} v${s.version}`} />)}
            </Technical>
          </section>
        ))}
      </div>
    </>
  );
}

function Fact({ label, value, big }: { label: string; value: string; big?: boolean }) {
  return (
    <div className="col" style={{ gap: 2 }}>
      <span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>{label}</span>
      <span className={big ? 'num' : undefined} style={{ fontSize: big ? 30 : 16, fontWeight: 600, overflowWrap: 'anywhere' }}>{value}</span>
    </div>
  );
}
