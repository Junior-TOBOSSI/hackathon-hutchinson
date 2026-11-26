/**
 * What the viewer follows: a mouse arrow on the laptop, a fingertip on the tablet.
 * Both show a ripple when they click / tap.
 */
export function MouseArrow({ x, y, pressed }: { x: number; y: number; pressed: boolean }) {
  return (
    <svg width="44" height="44" viewBox="0 0 24 24" style={{ position: 'absolute', left: x - 6, top: y - 3, transform: `scale(${pressed ? 0.88 : 1})`, transformOrigin: '6px 3px', filter: 'drop-shadow(0 3px 4px rgba(0,0,0,.35))' }}>
      <path d="M5 2l14 10.5-6.2 1 3.6 7-2.8 1.4-3.6-7L5 19.5z" fill="#fff" stroke="#0b1f3f" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export function Fingertip({ x, y, opacity, pressed }: { x: number; y: number; opacity: number; pressed: boolean }) {
  const size = pressed ? 58 : 68;
  return (
    <div style={{ position: 'absolute', left: x - size / 2, top: y - size / 2, width: size, height: size, borderRadius: '50%', background: 'rgba(255, 255, 255, 0.55)', border: '3px solid rgba(11, 31, 63, 0.55)', boxShadow: '0 8px 18px rgba(0,0,0,.25)', opacity }} />
  );
}

/** Expanding ring at the click point; `t` goes 0 → 1 over the ripple. */
export function Ripple({ x, y, t }: { x: number; y: number; t: number }) {
  if (t <= 0 || t >= 1) return null;
  const r = 20 + 50 * t;
  return <div style={{ position: 'absolute', left: x - r, top: y - r, width: 2 * r, height: 2 * r, borderRadius: '50%', border: '4px solid var(--red)', opacity: 1 - t }} />;
}
