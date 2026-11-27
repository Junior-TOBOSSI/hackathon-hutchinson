import { deploymentApi } from '../../api/deployment';
import { useResource } from './data';

// These resources use the existing AI Leader store: last valid response survives a failed refresh.
// fetchedAt here is the HOVIS API read time; Databricks freshness comes from the MLOps resources.
const read = <T,>(fn: (signal: AbortSignal) => Promise<T>) =>
  ({ signal }: { signal: AbortSignal }) => fn(signal).then((data) => ({
    data, meta: { fetchedAt: new Date().toISOString(), cache: null },
  }));

export const useDeploymentHistory = () =>
  useResource('deployment-history', read((signal) => deploymentApi.history(undefined, signal)));
export const useDeploymentOperation = (id: string | null) =>
  useResource(id ? `deployment-operation:${id}` : null,
    read((signal) => deploymentApi.get(id as string, signal)));
export const useDeploymentEvents = (id: string | null) =>
  useResource(id ? `deployment-events:${id}` : null,
    read((signal) => deploymentApi.events(id as string, signal)));
export const useDecisionHistory = (modelId: string | null, version: string | null) =>
  useResource(modelId && version ? `decision-history:${modelId}:${version}` : null,
    read((signal) => deploymentApi.decisionHistory(modelId as string, version as string, signal)));
export const useEdgeStations = () =>
  useResource('deployment-edge-stations', read(deploymentApi.edgeStations));

export const useEdgeStation = (id: string | null) =>
  useResource(id ? `deployment-edge-station:${id}` : null,
    read((signal) => deploymentApi.edgeStation(id as string, signal)));

export const useEdgeModelStatus = (id: string | null) =>
  useResource(id ? `deployment-edge-models:${id}` : null,
    read((signal) => deploymentApi.edgeModelStatus(id as string, signal)));
