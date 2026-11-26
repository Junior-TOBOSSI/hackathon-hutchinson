import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { coreApi } from "./core";
import { edgeApi } from "./edge";
import type { CorrectionIn } from "./types";

export const keys = {
  shift: (stationId: string) => ["edge", "shift", stationId] as const,
  parts: (stationId: string) => ["edge", "parts", stationId] as const,
  stations: ["core", "stations"] as const,
  alerts: ["core", "alerts"] as const,
  models: ["core", "models"] as const,
  deployments: ["core", "deployments"] as const,
  monitoring: ["core", "monitoring"] as const,
};

export const useCurrentShift = (stationId: string) =>
  useQuery({ queryKey: keys.shift(stationId), queryFn: () => edgeApi.currentShift(stationId) });

export const useParts = (stationId: string, limit = 20) =>
  useQuery({ queryKey: keys.parts(stationId), queryFn: () => edgeApi.parts({ station_id: stationId, limit }) });

export function useCorrectPart(stationId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ partId, body }: { partId: string; body: CorrectionIn }) => edgeApi.correctPart(partId, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.parts(stationId) });
      void client.invalidateQueries({ queryKey: keys.shift(stationId) });
    },
  });
}

export const useStations = () => useQuery({ queryKey: keys.stations, queryFn: coreApi.stations });
export const useAlerts = () => useQuery({ queryKey: keys.alerts, queryFn: () => coreApi.alerts() });
export const useModels = () => useQuery({ queryKey: keys.models, queryFn: coreApi.models });
export const useDeployments = () => useQuery({ queryKey: keys.deployments, queryFn: coreApi.deployments });
export const useMonitoring = () => useQuery({ queryKey: keys.monitoring, queryFn: () => coreApi.monitoring() });
