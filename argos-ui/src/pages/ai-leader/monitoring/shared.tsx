import { useSearchParams } from 'react-router-dom';
import { monitoring, type DataKind, type DriftStatus, type Filters, type SourceStatus } from '../../../api/monitoring';
import { read, useResource, type Resource } from '../data';
import { Chip } from '../ui';

/* Ressources Monitoring (store DBX-PERF-01) : clés préfixées « mon: », chargées à la demande.
   Aucune lecture n'écrit côté serveur ; collecte et gel de référence sont des POST explicites. */

const fkey = (f: Filters) => [f.data_kind, f.granularity, f.use_case, f.model_key, f.version, f.station, f.start, f.end].map((v) => v ?? '').join('|');

export const useSummary = (kind: string | null) => useResource(kind ? `mon:summary:${kind}` : null, read((o) => monitoring.summary(kind as string, o)));
export const useCatalog = (f: Filters | null) => useResource(f ? `mon:models:${fkey({ ...f, model_key: undefined, version: undefined, granularity: undefined })}` : null, read((o) => monitoring.models(f as Filters, o)));
export const useInferences = (f: Filters | null) => useResource(f ? `mon:inf:${fkey(f)}` : null, read((o) => monitoring.inferences(f as Filters, o)));
export const useHuman = (f: Filters | null) => useResource(f ? `mon:human:${fkey(f)}` : null, read((o) => monitoring.human(f as Filters, o)));
export const useAlerts = () => useResource('mon:alerts', read(monitoring.alerts));
export const useHistory = (kind: DataKind | null) => useResource(kind ? `mon:history:${kind}` : null, read((o) => monitoring.history(kind as DataKind, o)));
export const useModelDetail = (key: string | null, kind: string) => useResource(key ? `mon:model:${key}:${kind}` : null, read((o) => monitoring.model(key as string, kind, o)));
export const usePerformance = (id: string | null) => useResource(id ? `mon:perf:${id}` : null, read((o) => monitoring.performance(id as string, o)));
export const useSignals = (id: string | null) => useResource(id ? `mon:signals:${id}` : null, read((o) => monitoring.signals(id as string, o)));
export const useDrift = (p: { model_key: string; version: string; data_kind: DataKind; reference_id?: string } | null) =>
  useResource(p ? `mon:drift:${p.model_key}|${p.version}|${p.data_kind}|${p.reference_id ?? ''}` : null, read((o) => monitoring.drift(p as NonNullable<typeof p>, o)));

/** URL state: ?section=monitoring&key=<model key>&tab=<tab> */
export function useMonParams() {
  const [params, setParams] = useSearchParams();
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) if (v) next.set(k, v); else next.delete(k);
    setParams(next);
  };
  return { key: params.get('key'), tab: params.get('tab') ?? 'overview', set };
}

/* ------------------------------------------------------------------ libellés */

export const DECISIONS: { id: string; label: string; color: string }[] = [
  { id: 'conforme', label: 'OK (conforme)', color: 'var(--green)' },
  { id: 'anomalie', label: 'NOK (anomalie)', color: 'var(--red)' },
  { id: 'a_verifier', label: 'À vérifier', color: 'var(--amber)' },
];

const DRIFT: Record<DriftStatus, [string, 'green' | 'red' | 'amber' | 'grey' | 'blue' | 'navy', string]> = {
  alert: ['Alerte', 'red', 'Au moins un indicateur dépasse le seuil d’alerte.'],
  watch: ['À surveiller', 'amber', 'Un indicateur dépasse le seuil de surveillance.'],
  stable: ['Stable', 'green', 'Indicateurs sous les seuils, effectifs suffisants.'],
  available: ['Évaluée', 'green', 'Mesures calculées.'],
  reference_absent: ['Référence absente', 'grey', 'Aucune référence figée pour cette version : aucune dérive ne peut être évaluée.'],
  insufficient_reference: ['Référence insuffisante', 'amber', 'La référence compte moins d’observations que le minimum : pas d’alerte fiable.'],
  insufficient_current: ['Effectif insuffisant', 'amber', 'La population observée est trop petite : pas d’alerte fiable.'],
  incompatible: ['Incompatible', 'red', 'La référence ne peut pas être comparée à cette population.'],
  mixed_data: ['Données mélangées', 'amber', 'Choisissez une origine (réelle ou simulée) pour évaluer la dérive.'],
  no_production_data: ['Sans inférence associée', 'grey', 'Aucune inférence de production n’est rattachée à ce modèle du registre.'],
};
export const driftLabel = (s: DriftStatus | string) => DRIFT[s as DriftStatus]?.[0] ?? s;
export const driftHelp = (s: DriftStatus | string) => DRIFT[s as DriftStatus]?.[2] ?? '';
export const DriftChip = ({ status }: { status: DriftStatus | string }) => {
  const d = DRIFT[status as DriftStatus];
  return <Chip tone={d?.[1] ?? 'grey'} title={d?.[2]}>{d?.[0] ?? status}</Chip>;
};

const REASONS: Record<string, string> = {
  'reference belongs to another model / version': 'la référence appartient à un autre modèle ou une autre version',
  'incompatible score definitions': 'les définitions de score sont différentes',
  'synthetic / simulated data compared with real data': 'données synthétiques ou simulées comparées à des données réelles',
  'filter real or simulated data to evaluate the drift': 'filtrez les données réelles ou simulées pour évaluer la dérive',
};
export const reasonFr = (r: string) => REASONS[r] ?? r;

export const USE_CASES: [string, string][] = [['quality', 'Qualité'], ['safety', 'Sécurité (EPI)'], ['workstation', 'Poste de travail / 5S']];
export const useCaseFr = (u: string | null | undefined) => USE_CASES.find(([id]) => id === u)?.[1] ?? u ?? '—';

export const PERIODS: [string, string][] = [['all', 'Toute la période'], ['1', '24 dernières heures'], ['7', '7 derniers jours'], ['30', '30 derniers jours']];
export const periodLabel = (p: string) => PERIODS.find(([id]) => id === p)?.[1] ?? p;
export const startOf = (p: string) => (p === 'all' ? undefined : new Date(Date.now() - Number(p) * 86400_000).toISOString());

export const OriginChip = ({ kind }: { kind: DataKind | 'all' }) =>
  kind === 'simulated' ? <Chip tone="amber" title="Événements produits par la simulation des postes : pas des mesures de production">Données simulées</Chip>
    : kind === 'real' ? <Chip tone="green">Production réelle</Chip> : <Chip tone="grey">Toutes origines</Chip>;

export const SourceChip = ({ status }: { status: string | undefined }) =>
  status === 'available' ? <Chip tone="green">Disponible</Chip> : status === 'partial' ? <Chip tone="amber" title="Lecture tronquée (limite de l’API Core) : agrégation partielle">Partiel</Chip>
    : status === 'unavailable' ? <Chip tone="red">Indisponible</Chip> : <Chip tone="grey">…</Chip>;

/* ------------------------------------------------------------------ formats */

export const dt = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '—');
export const day = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' }) : '—');
export const time = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleTimeString('fr-FR') : '—');
export const ms = (v: number | null | undefined) => (v == null ? '—' : `${v.toFixed(v < 10 ? 1 : 0).replace('.', ',')} ms`);
export const pct = (v: number | null | undefined, digits = 1) => (v == null ? '—' : `${(v * 100).toFixed(digits).replace('.', ',')} %`);
export const num = (v: number | null | undefined, digits = 3) => (v == null ? '—' : Number.isInteger(v) ? v.toLocaleString('fr-FR') : v.toFixed(digits).replace('.', ','));
export const shortKey = (key: string) => key.replace(/^unassociated:[^:]+:/, '').replace(/^registry:/, '');

/** Core freshness line, from the payload `sources` (the Core is not Databricks: no cache header). */
export function SourceLine({ sources, res }: { sources?: SourceStatus[]; res?: Resource<unknown> }) {
  const core = sources?.find((s) => s.name === 'core');
  return (
    <span className="muted" style={{ fontSize: 12 }}>
      {core ? `Core lu à ${time(core.fetched_at)}` : 'Core —'}
      {core?.detail ? ` · ${core.detail}` : ''}
      {res?.refreshing ? ' · actualisation…' : ''}
      {res?.staleError ? ` · dernière actualisation en échec : ${res.staleError}` : ''}
    </span>
  );
}
