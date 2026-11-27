import type { StationIssue, StationLive } from '../api/types';

/** Une action à afficher à l'opérateur, dans l'ordre où il doit la faire. */
export interface OperatorAction {
  key: string;
  title: string; // « Mettez vos lunettes »
  subtitle: string; // « Sécurité · EPI manquant »
  strong: boolean; // rouge plein (sécurité, pièce) ou atténué (poste)
}

const RANK: Record<StationIssue['category'], number> = {
  SECURITE_EPI: 0, COMPORTEMENT: 0, SIGNALEMENT: 1, QUALITE: 2, POSTE: 3, RYTHME: 4, EQUIPEMENT: 5,
};
const SUB: Record<StationIssue['category'], string> = {
  SECURITE_EPI: 'Sécurité · EPI manquant', COMPORTEMENT: 'Sécurité · comportement', POSTE: 'Poste de travail · objet étranger',
  QUALITE: 'Qualité', RYTHME: 'Rythme', EQUIPEMENT: 'Équipement', SIGNALEMENT: 'Signalement',
};

/**
 * Règle de priorité quand plusieurs problèmes arrivent en même temps :
 * 1. la sécurité (EPI, comportement)  2. la pièce KO  3. le poste de travail.
 */
export function operatorActions(live: StationLive): OperatorAction[] {
  const list: (OperatorAction & { rank: number })[] = live.issues.map((i) => ({
    key: i.id, title: i.instruction, subtitle: SUB[i.category], strong: RANK[i.category] <= 2, rank: RANK[i.category],
  }));
  if (live.part.verdict === 'KO') {
    list.push({ key: 'piece', title: 'Pièce KO au bac rebuts', subtitle: 'Qualité · voir l’image de la pièce', strong: true, rank: 2 });
  }
  return list.sort((a, b) => a.rank - b.rank);
}
