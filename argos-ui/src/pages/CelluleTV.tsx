import { useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { StationSummary } from '../api/types';
import { HovisLogo } from '../components/brand';
import { Clock, deltaText, fmt, Loading } from '../components/ui';
import { useApi } from '../hooks/useApi';

/**
 * Écran TV de la cellule, au bord de la ligne de production, sans connexion personnelle.
 * Uniquement la PERFORMANCE des postes, pour suivre la production de la cellule :
 * pas d'alerte sécurité, pas d'image, pas de nom. Les postes restent dans leur ordre
 * (jamais de classement). Route : /tv/:cellId
 */
const TOLERANCE = 10; // pièces de retard tolérées avant de passer à l'orange

/**
 * Couleur d'état d'un poste. `bg` colore toute la tuile ; `fg` est la couleur du texte posé dessus,
 * choisie pour un contraste d'au moins 5:1 (lisible à plusieurs mètres) :
 * vert foncé + blanc 5,4:1 · orange + marine 6,1:1 · rouge + blanc 5,9:1.
 * `text` sert pour un chiffre écrit en couleur sur le fond marine (bandeau du haut).
 */
function tone(delta: number) {
  if (delta >= 0) return { bg: 'var(--green-text)', fg: '#fff', text: 'var(--green-light)', label: 'dans le rythme' };
  if (delta >= -TOLERANCE) return { bg: 'var(--amber)', fg: 'var(--navy)', text: '#ffd28a', label: 'léger retard' };
  return { bg: 'var(--red)', fg: '#fff', text: 'var(--red-light)', label: 'en retard' };
}

export default function CelluleTV() {
  const { cellId = 'C3' } = useParams();
  const { data: cell } = useApi(() => api.cellOverview(cellId), [cellId], 30000);
  if (!cell) return <Loading />;

  const good = cell.stations.reduce((s, st) => s + st.good, 0);
  const target = cell.stations.reduce((s, st) => s + st.target, 0);
  const expected = cell.stations.reduce((s, st) => s + st.expectedNow, 0);
  const ko = cell.stations.reduce((s, st) => s + st.ko, 0);
  const delta = good - expected;
  const t = tone(delta);

  return (
    <div style={{ minHeight: '100vh', background: 'var(--navy)', color: '#fff', padding: '32px 48px', display: 'flex', flexDirection: 'column', gap: 26 }}>
      <div className="row" style={{ gap: 22 }}>
        <HovisLogo size={44} tone="light" />
        <span style={{ width: 1, height: 44, background: 'var(--navy-line)' }} />
        <span className="col" style={{ gap: 2 }}>
          <span className="cond" style={{ fontWeight: 700, fontSize: 40, lineHeight: 1 }}>{cell.cell.name.toUpperCase()}</span>
          <span style={{ color: 'var(--on-navy-muted)', fontSize: 18 }}>{cell.uap.name} · shift {cell.currentShift.code} · {cell.currentShift.start} – {cell.currentShift.end}</span>
        </span>
        <span style={{ flex: 1 }} />
        <span style={{ background: 'var(--navy-2)', padding: '6px 18px', borderRadius: 14 }}><Clock iso={new Date().toISOString()} /></span>
      </div>

      {/* La cellule : avancement, rythme, KO */}
      <div className="row" style={{ gap: 26, alignItems: 'stretch' }}>
        <div className="col grow" style={{ background: 'var(--navy-2)', borderRadius: 28, padding: '22px 30px', gap: 16 }}>
          <div className="between" style={{ alignItems: 'baseline' }}>
            <span style={{ fontSize: 22, color: 'var(--on-navy-muted)', letterSpacing: '0.16em', textTransform: 'uppercase' }}>Pièces bonnes du shift</span>
            <span className="num" style={{ fontSize: 64 }}>{fmt(good)} <span style={{ fontSize: 30, color: 'var(--on-navy-muted)' }}>/ {fmt(target)}</span></span>
          </div>
          <div style={{ position: 'relative', height: 34, borderRadius: 12, background: 'rgba(255,255,255,.1)' }}>
            <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${(good / target) * 100}%`, borderRadius: 12, background: t.bg }} />
            <div title="Attendu maintenant" style={{ position: 'absolute', left: `calc(${(expected / target) * 100}% - 2px)`, top: -6, bottom: -6, width: 4, borderRadius: 2, background: '#fff' }} />
          </div>
          <span style={{ color: 'var(--on-navy-muted)', fontSize: 16 }}>Trait blanc : où la cellule devrait être maintenant ({fmt(expected)} pièces)</span>
        </div>
        <Big label="Rythme" value={deltaText(delta, true)} color={t.text} />
        <Big label="Pièces KO" value={fmt(ko)} sub={`taux ${((ko / (good + ko)) * 100).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} %`} />
      </div>

      {/* Les postes, dans leur ordre physique */}
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 18 }}>
        {cell.stations.map((s) => <StationTile key={s.id} s={s} />)}
      </div>

      <div className="between" style={{ color: 'var(--on-navy-muted)', fontSize: 15 }}>
        <span>
          <Swatch c="var(--green-text)" /> dans le rythme · <Swatch c="var(--amber)" /> jusqu’à {TOLERANCE} pièces de retard · <Swatch c="var(--red)" /> plus de {TOLERANCE} pièces de retard
        </span>
        <span>Performance des postes uniquement · mise à jour toutes les 30 s</span>
      </div>
    </div>
  );
}

function Big({ label, value, sub, color = '#fff' }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="col" style={{ width: 340, background: 'var(--navy-2)', borderRadius: 28, padding: '22px 30px', gap: 10, justifyContent: 'center' }}>
      <span style={{ fontSize: 22, color: 'var(--on-navy-muted)', letterSpacing: '0.16em', textTransform: 'uppercase' }}>{label}</span>
      <span className="num" style={{ fontSize: 52, color }}>{value}</span>
      {sub && <span style={{ fontSize: 20, color: 'var(--on-navy-muted)' }}>{sub}</span>}
    </div>
  );
}

/** Tuile d'un poste : entièrement colorée selon son rythme, pour être lue de loin. */
function StationTile({ s }: { s: StationSummary }) {
  const delta = s.good - s.expectedNow;
  const t = tone(delta);
  const pct = (s.good / s.target) * 100;
  return (
    <div className="col" style={{ background: t.bg, color: t.fg, borderRadius: 24, padding: '18px 20px', gap: 12 }}>
      <div className="between" style={{ alignItems: 'baseline' }}>
        <span className="cond" style={{ fontWeight: 700, fontSize: 40 }}>{s.id.split('·')[1]}</span>
        <span style={{ fontSize: 20, fontWeight: 600 }}>{Math.round(pct)} %</span>
      </div>
      {/* Barre d'avancement dans la couleur du texte, trait = attendu maintenant */}
      <div style={{ position: 'relative', height: 14, borderRadius: 7, background: 'rgba(255,255,255,.28)' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${pct}%`, borderRadius: 7, background: t.fg }} />
        <div style={{ position: 'absolute', left: `${(s.expectedNow / s.target) * 100}%`, top: -5, bottom: -5, width: 4, borderRadius: 2, background: t.fg, opacity: 0.6 }} />
      </div>
      <span className="num" style={{ fontSize: 32 }}>{deltaText(delta, true)}</span>
      <span style={{ fontSize: 19, fontWeight: 500 }}>{s.good} bonnes · {s.ko} KO</span>
    </div>
  );
}

const Swatch = ({ c }: { c: string }) => <span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 3, background: c, margin: '0 4px -1px 0' }} />;
