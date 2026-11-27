import { useState } from 'react';
import type { EdgeStation } from '../../api/deployment';
import type { ManagedModel, ModelStatus } from '../../api/mlops';
import { Unavailable } from './common';
import { decisionOf } from './lifecycleCatalog';
import { Chip, fr, SelectField } from './ui';

const STEPS = ['Machines', 'Cas d’usage', 'Modèle', 'Version approuvée', 'Compatibilité', 'Récapitulatif', 'Confirmation'] as const;

/** Preparation-only assistant. No Edge deployment API exists yet. */
export default function FleetWizard({ stations, models, statuses, onClose }: {
  stations: EdgeStation[]; models: ManagedModel[]; statuses: ModelStatus[]; onClose: () => void;
}) {
  const [step, setStep] = useState(0);
  const [ids, setIds] = useState(stations.map((station) => station.station_id));
  const [useCase, setUseCase] = useState('');
  const [modelId, setModelId] = useState('');
  const [version, setVersion] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const candidates = models.filter((model) => model.argos_use_case === useCase);
  const model = candidates.find((item) => item.id === modelId) ?? null;
  const approved = statuses.find((item) => item.model_id === modelId)?.versions
    .filter((item) => decisionOf(item) === 'approved').map((item) => item.version.version) ?? [];
  const chosen = stations.filter((station) => ids.includes(station.station_id));
  const offline = chosen.filter((station) => !station.online);
  const nextAllowed = step === 0 ? ids.length > 0 : step === 1 ? !!useCase
    : step === 2 ? !!model : step === 3 ? !!version : true;
  return <div className="lifecycle-overlay" onClick={onClose}><section className="card lifecycle-wizard col" onClick={(event) => event.stopPropagation()} style={{ gap: 14 }}>
    <header className="between"><div><h2 className="h2">Préparer un déploiement Edge groupé</h2>
      <span className="muted">Aucune distribution ni mutation Edge n’est disponible à cette étape.</span></div>
      <button className="btn btn-ghost" aria-label="Fermer" onClick={onClose}>✕</button></header>
    <div className="lifecycle-steps">{STEPS.map((name, index) => <span className={index === step ? 'active' : ''} key={name}>{index + 1}. {name}</span>)}</div>
    {step === 0 && <div className="col" style={{ gap: 8 }}><b>Machines sélectionnées</b>{stations.map((station) => <label key={station.station_id} className="lifecycle-operation-row">
      <span><input type="checkbox" checked={ids.includes(station.station_id)} onChange={() => setIds((current) => current.includes(station.station_id)
        ? current.filter((id) => id !== station.station_id) : [...current, station.station_id])} /> {station.station_id}</span>
      <Chip tone={station.online ? 'green' : 'amber'}>{station.online ? 'Connectée' : 'Hors ligne'}</Chip></label>)}</div>}
    {step === 1 && <div className="col" style={{ gap: 9 }}><b>Cas d’usage à déployer</b><SelectField label="Cas d’usage" value={useCase} allLabel="Choisir un cas d’usage" onChange={(value) => { setUseCase(value); setModelId(''); setVersion(''); }}
      options={[["quality", fr('quality')], ["safety", fr('safety')], ["workstation", fr('workstation')]]} /></div>}
    {step === 2 && <div className="col" style={{ gap: 9 }}><b>Modèle enregistré</b><SelectField label="Modèle" value={modelId} allLabel="Choisir un modèle industriel" onChange={(value) => { setModelId(value); setVersion(''); }}
      options={candidates.map((item) => [item.id, `${item.display_name} · ${item.uc_name}`])} />
      {!candidates.length && <Unavailable tone="grey">Aucun modèle industriel configuré pour ce cas d’usage. Les modèles synthétiques sont exclus.</Unavailable>}</div>}
    {step === 3 && <div className="col" style={{ gap: 9 }}><b>Version numérique approuvée</b><SelectField label="Version approuvée" value={version} allLabel="Choisir une version" onChange={setVersion}
      options={approved.map((value) => [value, `v${value}`])} />
      {!approved.length && <Unavailable tone="grey">Aucune version approuvée disponible dans le Registry pour ce modèle.</Unavailable>}</div>}
    {step === 4 && <div className="col" style={{ gap: 10 }}><b>Contrôles de compatibilité</b>
      <div className="dataset-mini-kpis"><Fact label="Machines sélectionnées" value={String(chosen.length)} />
        <Fact label="Hors ligne" value={String(offline.length)} />
        <Fact label="Compatibles" value="Indisponible" /><Fact label="Incompatibles" value="Indisponible" /></div>
      <Unavailable tone="amber">Le Core ne connaît ni le runtime du poste, ni la version souhaitée, ni la validation du package. La compatibilité ne peut pas être confirmée. Les machines hors ligne ne peuvent pas recevoir un déploiement immédiat.</Unavailable>
    </div>}
    {step === 5 && <div className="col" style={{ gap: 9 }}><b>Récapitulatif de la demande</b>
      <div className="dataset-mini-kpis"><Fact label="Machines" value={chosen.map((station) => station.station_id).join(', ') || 'Aucune'} />
        <Fact label="Cas d’usage" value={fr(useCase)} /><Fact label="Modèle" value={model?.display_name ?? 'Indisponible'} />
        <Fact label="Version demandée" value={version ? `v${version}` : 'Indisponible'} /></div>
      <b>Suivi individuel prévu</b>{chosen.map((station) => <div key={station.station_id} className="lifecycle-operation-row">
        <span>{station.station_id}</span><Chip tone={station.online ? 'grey' : 'amber'}>{station.online ? 'Confirmation individuelle indisponible' : 'Hors ligne'}</Chip>
      </div>)}
      <Unavailable tone="grey">Chaque machine devra disposer de son propre statut et de sa propre confirmation model.status. Une réussite globale ne peut pas être déduite de l’envoi d’une demande.</Unavailable></div>}
    {step === 6 && <div className="col" style={{ gap: 10 }}><b>Confirmation explicite</b>
      <label><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} /> J’ai vérifié la sélection et la version demandée.</label>
      <Unavailable tone="amber">Confirmation indisponible : le backend de distribution Edge et ses contrôles de compatibilité ne sont pas encore implémentés. Aucun package n’a été transféré.</Unavailable>
      <button className="btn btn-primary" disabled title="Backend Edge requis">Confirmer le déploiement</button></div>}
    <div className="row" style={{ justifyContent: 'space-between', gap: 8 }}><button className="btn btn-ghost" disabled={step === 0} onClick={() => setStep(step - 1)}>Précédent</button>
      {step < STEPS.length - 1 && <button className="btn btn-primary" disabled={!nextAllowed} onClick={() => setStep(step + 1)}>Suivant</button>}</div>
  </section></div>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="dataset-mini"><span className="muted">{label}</span><b>{value}</b></div>;
}
