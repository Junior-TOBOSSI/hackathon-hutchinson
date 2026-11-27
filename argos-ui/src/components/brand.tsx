/*
 * Identité HOVIS, redessinée en SVG d'après la fiche de construction de la charte
 * (grille 120 × 120 u) : deux fûts 4,5 × 84 u, une lentille faite de deux arcs
 * R 48,6 u sur un axe incliné à 10°, une ouverture Ø 15 u (trait 1,2 u) et un
 * point de détection Ø 6,8 u en Rouge Signal.
 * Le SVG reste net à toutes les tailles et suit la couleur du fond (marine ou blanc).
 */

// Pointes de la lentille : sur l'axe à 10° qui passe par le centre (60, 60).
const LEFT_TIP = '28.5 65.6';
const RIGHT_TIP = '91.5 54.4';

/** Symbole seul : le H dont la barre est un œil. */
export function HovisMark({ size = 40, color = 'var(--navy)', title }: { size?: number; color?: string; title?: string }) {
  // Petites tailles : traits épaissis pour rester lisibles (comme la planche "petites tailles" de la charte).
  const small = size < 56;
  const stem = small ? 7 : 4.5;
  const lens = small ? 3.6 : 2;
  const ring = small ? 2.4 : 1.2;
  const dot = small ? 4.4 : 3.4;
  return (
    <svg
      width={(size * 84) / 88}
      height={size}
      viewBox="18 16 84 88"
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      style={{ flexShrink: 0, display: 'block' }}
    >
      <rect x={28.5 - stem} y="18" width={stem} height="84" fill={color} />
      <rect x="91.5" y="18" width={stem} height="84" fill={color} />
      <path
        d={`M ${LEFT_TIP} A 48.6 48.6 0 0 1 ${RIGHT_TIP} A 48.6 48.6 0 0 1 ${LEFT_TIP} Z`}
        fill="none"
        stroke={color}
        strokeWidth={lens}
        strokeLinejoin="round"
      />
      <circle cx="60" cy="60" r="7.5" fill="none" stroke={color} strokeWidth={ring} />
      <circle cx="60" cy="60" r={dot} fill="var(--red)" />
    </svg>
  );
}

/**
 * Logo ARGOS (image fournie par l'équipe, détourée sur fond transparent) :
 * `tone="light"` pour un fond marine (lettres blanches), `tone="dark"` pour un fond blanc.
 * `size` : hauteur de référence (comme l'ancien logo) ; la signature est en option.
 * Le nom `HovisLogo` est gardé pour les écrans qui l'importent.
 */
export function ArgosLogo({ size = 40, tone = 'light', tagline = false }: { size?: number; tone?: 'light' | 'dark'; tagline?: boolean }) {
  const soft = tone === 'light' ? 'var(--on-navy-muted)' : 'var(--muted)';
  const height = Math.round(size * 0.8);
  return (
    <span role="img" aria-label="ARGOS" style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'flex-start', gap: size * 0.14 }}>
      <img src={tone === 'light' ? '/img/argos-logo-light.png' : '/img/argos-logo-dark.png'} alt="" aria-hidden="true"
        style={{ height, width: 'auto', display: 'block' }} />
      {tagline && (
        <span aria-hidden="true" style={{ color: soft, fontWeight: 400, fontSize: Math.max(10, size * 0.14), letterSpacing: '0.28em', whiteSpace: 'nowrap' }}>
          SMARTER VISION. SAFER INDUSTRY.
        </span>
      )}
    </span>
  );
}

export const HovisLogo = ArgosLogo;
