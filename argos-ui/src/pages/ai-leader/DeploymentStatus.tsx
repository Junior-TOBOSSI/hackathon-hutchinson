import type { DeploymentOperation } from '../../api/deployment';
import { Chip } from './ui';

const LABELS: Record<string, string> = { prepared: 'préparée', requesting: 'demande envoyée', updating: 'mise à jour', verifying: 'vérification',
  succeeded: 'réussie', failed: 'échouée', uncertain: 'incertaine', expired: 'expirée' };
export const operationStatusLabel = (status: string) => LABELS[status] ?? status;

export function OperationBadge({ operation }: { operation: DeploymentOperation }) {
  const tone = operation.status === 'succeeded' ? 'green' : operation.status === 'failed' ? 'red'
    : operation.status === 'uncertain' ? 'amber' : 'blue';
  return <Chip tone={tone}>{operationStatusLabel(operation.status)}</Chip>;
}
