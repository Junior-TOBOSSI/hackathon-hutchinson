import type { EdgeModelStatus, EdgeStation } from '../../api/deployment';

export const USE_CASES = ['quality', 'safety', 'workstation'] as const;
export type IndustrialUseCase = typeof USE_CASES[number];

export const stationModel = (station: EdgeStation, useCase: string) =>
  station.models.find((model) => model.use_case === useCase) ?? null;

/** Core has no desired-version projection yet: do not infer it from the UC champion. */
export function modelState(station: EdgeStation, useCase: string): string {
  const item = stationModel(station, useCase);
  if (!item) return 'État inconnu';
  if (item.status === 'failed') return 'Erreur';
  if (!station.online && item.status === 'loaded') return 'Dernière version connue';
  if (item.status === 'loading') return 'Chargement';
  if (item.status === 'absent') return 'Non chargé';
  return item.model ? 'Chargé · version souhaitée inconnue' : 'Chargé · référence inconnue';
}

export function modelText(station: EdgeStation, useCase: string): string {
  const item = stationModel(station, useCase);
  if (!item) return 'État inconnu';
  if (!item.model) return item.status === 'absent' ? 'Non chargé' : 'Référence indisponible';
  return `${item.model.registered_model} · v${item.model.version}`;
}

export function rawModelText(item: EdgeModelStatus): string {
  return `${item.model_name} · ${/^\d+$/.test(item.model_version) ? `v${item.model_version}` : item.model_version}`;
}

export function filterStations(stations: EdgeStation[], filters: {
  query: string; cell: string; model: string; useCase: string; connection: string; version: string; sort: string;
}): EdgeStation[] {
  const query = filters.query.trim().toLocaleLowerCase('fr');
  return stations.filter((station) =>
    (!query || `${station.station_id} ${station.name}`.toLocaleLowerCase('fr').includes(query))
    && (!filters.cell || station.cell === filters.cell)
    && (!filters.connection || (filters.connection === 'online' ? station.online : !station.online))
    && (!filters.useCase || !!stationModel(station, filters.useCase))
    && (!filters.model || station.models.some((item) => item.model?.registered_model === filters.model))
    && (!filters.version || station.models.some((item) => item.model?.version === filters.version)))
    .sort((a, b) => filters.sort === 'lastSeen'
      ? (b.last_seen_at ?? '').localeCompare(a.last_seen_at ?? '')
      : filters.sort === 'connection' ? Number(b.online) - Number(a.online) || a.station_id.localeCompare(b.station_id)
        : filters.sort === 'cell' ? a.cell.localeCompare(b.cell) || a.station_id.localeCompare(b.station_id)
          : a.station_id.localeCompare(b.station_id));
}
