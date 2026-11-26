import { Badge, grid, KV, LinkButton, Loading, Panel, Technical, Unavailable, useNav } from './common';
import { useCatalogs, useRunMap, useSchemas } from './data';
import { useSelection } from './selection';

/* Datasets : uniquement ce que les API actuelles exposent (paramètres et tags des runs
   MLflow, catalogue Unity Catalog). Gestion et versionnement = chantier suivant. */

interface DatasetUse { version: string; splits: Record<string, number>; manifest: string | null; usedBy: string[] }

export default function Datasets() {
  const { go } = useNav();
  const { model, status, loading, error, statusLoading, statusError } = useSelection();
  const runIds = (status?.versions ?? []).map((v) => v.version.run_id).filter((x): x is string => !!x);
  const runs = useRunMap(runIds);
  const catalogs = useCatalogs();
  const catalog = model?.uc_name.split('.')[0] ?? null;
  const schemas = useSchemas(catalog);

  if (error) return <Unavailable tone="red">{error}</Unavailable>;
  if (loading || !model) return <Loading />;

  const datasets = new Map<string, DatasetUse>();
  for (const vs of status?.versions ?? []) {
    const run = vs.version.run_id ? runs.data?.[vs.version.run_id] : undefined;
    if (!run) continue;
    const version = run.params.dataset_version ?? vs.version.tags.argos_dataset_version;
    if (!version) continue;
    const entry = datasets.get(version) ?? { version, splits: {}, manifest: run.tags['argos.manifest_sha256'] ?? null, usedBy: [] };
    for (const [k, label] of [['n_train', 'entraînement'], ['n_validation', 'validation'], ['n_test', 'test']] as const) {
      if (run.params[k] != null) entry.splits[label] = Number(run.params[k]);
    }
    entry.usedBy.push(`v${vs.version.version}`);
    datasets.set(version, entry);
  }
  const modelSchema = model.uc_name.split('.').slice(0, 2).join('.');

  return (
    <>
      <Panel title={`Données de ${model.display_name}`} sub="Déduit des runs MLflow des versions enregistrées"
        right={model.synthetic ? <Badge tone="amber">Données synthétiques</Badge> : undefined}>
        {statusError && <Unavailable tone="red">Registre indisponible : {statusError}</Unavailable>}
        {(statusLoading || runs.loading) && <Loading />}
        {runs.error && <Unavailable tone="red">{runs.error}</Unavailable>}
        {!statusLoading && !statusError && runs.data && datasets.size === 0 && <Unavailable tone="grey">Aucune version de dataset renseignée dans les runs de ce modèle.</Unavailable>}
        <div style={grid(320)}>
          {[...datasets.values()].map((d) => {
            const total = Object.values(d.splits).reduce((a, b) => a + b, 0);
            return (
              <div key={d.version} className="col" style={{ gap: 12, padding: 16, borderRadius: 16, background: 'var(--surface-soft)' }}>
                <div className="between"><span className="h2" style={{ fontSize: 22 }}>{d.version}</span><span className="muted">{total ? `${total} éléments` : ''}</span></div>
                {total > 0 && (
                  <>
                    <div style={{ display: 'flex', height: 16, borderRadius: 8, overflow: 'hidden' }}>
                      {Object.entries(d.splits).map(([k, n], i) => <div key={k} title={`${k} : ${n}`} style={{ width: `${(n / total) * 100}%`, background: ['var(--navy)', 'var(--primary-light)', 'var(--cat-rythme)'][i] }} />)}
                    </div>
                    <div className="row" style={{ gap: 14, fontSize: 14, flexWrap: 'wrap' }}>
                      {Object.entries(d.splits).map(([k, n]) => <span key={k}><b>{n}</b> {k}</span>)}
                    </div>
                  </>
                )}
                <span style={{ fontSize: 14 }}>Utilisé par {d.usedBy.join(', ')} · <LinkButton onClick={() => go('registry', model.id)}>versions</LinkButton> · <LinkButton onClick={() => go('training', model.id)}>entraînements</LinkButton></span>
                <Technical title="Empreinte et provenance"><KV k="SHA-256 du manifeste" v={d.manifest ?? 'non renseignée'} /></Technical>
              </div>
            );
          })}
        </div>
      </Panel>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: 18, alignItems: 'start' }}>
        <Panel title="Catalogue Unity Catalog" sub={catalog ? `Schémas du catalogue « ${catalog} »` : undefined}>
          {(catalogs.error || schemas.error) && <Unavailable tone="red">{catalogs.error ?? schemas.error}</Unavailable>}
          {schemas.loading && <Loading />}
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            {schemas.data?.filter((s) => s.name !== 'information_schema').map((s) => (
              <Badge key={s.full_name} tone={s.full_name === modelSchema ? 'blue' : 'grey'} title={s.comment ?? ''}>{s.full_name}{s.full_name === modelSchema ? ' · ce modèle' : ''}</Badge>
            ))}
          </div>
          {catalogs.data && <span className="muted" style={{ fontSize: 13 }}>Catalogues accessibles : {catalogs.data.join(', ')}</span>}
        </Panel>
        <Panel title="Gestion des datasets">
          <Unavailable tone="grey">
            À raccorder (prochain chantier) : liste des volumes et tables, aperçu des annotations, import, versionnement et lignage des datasets.
            Les API actuelles n'exposent pas encore ces informations.
          </Unavailable>
        </Panel>
      </div>
    </>
  );
}
