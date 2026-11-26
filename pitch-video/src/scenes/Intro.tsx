/**
 * Opening and closing scene: the HOVIS mark draws itself (stems grow, lens is traced,
 * the red detection dot pops), then the wordmark and the tagline appear.
 * Geometry is the one of argos-ui/src/components/brand.tsx (120 × 120 grid).
 */
import { useCurrentFrame } from 'remotion';
import { content } from '../content';
import { enter, progress, Scene, usePop } from '../kit';

const LENS = 'M 28.5 65.6 A 48.6 48.6 0 0 1 91.5 54.4 A 48.6 48.6 0 0 1 28.5 65.6 Z';
const LENS_LENGTH = 150; // approximate path length, enough for the stroke-dash trick

function AnimatedMark({ size }: { size: number }) {
  const frame = useCurrentFrame();
  const stems = progress(frame, 0.4, 0.8);
  const lens = progress(frame, 1.0, 1.0);
  const ring = progress(frame, 1.7, 0.5);
  const dot = usePop(2.1);
  return (
    <svg width={(size * 84) / 88} height={size} viewBox="18 16 84 88">
      {/* Stems grow from the centre line */}
      <rect x="24" y={60 - 42 * stems} width="4.5" height={84 * stems} fill="#fff" />
      <rect x="91.5" y={60 - 42 * stems} width="4.5" height={84 * stems} fill="#fff" />
      {/* Lens traced with a dash offset */}
      <path d={LENS} fill="none" stroke="#fff" strokeWidth="2" strokeLinejoin="round" strokeDasharray={LENS_LENGTH} strokeDashoffset={LENS_LENGTH * (1 - lens)} />
      <circle cx="60" cy="60" r="7.5" fill="none" stroke="#fff" strokeWidth="1.2" opacity={ring} />
      <circle cx="60" cy="60" r={3.4 * dot} fill="var(--red)" />
    </svg>
  );
}

export function Intro({ frames, closing = false }: { frames: number; closing?: boolean }) {
  const frame = useCurrentFrame();
  const letters = 'HOVIS'.split('');
  return (
    <Scene frames={frames} dark>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 70 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 90 }}>
          <AnimatedMark size={300} />
          <div style={{ width: 2, height: 300 * progress(frame, 2.4, 0.6), background: 'var(--on-navy-muted)', opacity: 0.4 }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 34 }}>
            <div style={{ display: 'flex', fontSize: 190, fontWeight: 400, lineHeight: 1 }}>
              {letters.map((l, i) => (
                <span key={i} style={{ marginRight: i < letters.length - 1 ? '0.32em' : 0, ...enter(frame, 2.6 + i * 0.12, 30) }}>{l}</span>
              ))}
            </div>
            <span style={{ fontSize: 40, letterSpacing: '0.3em', color: 'var(--on-navy-muted)', ...enter(frame, 3.6) }}>{content.tagline}</span>
          </div>
        </div>
        {closing && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18, ...enter(frame, 4.6) }}>
            <span style={{ fontSize: 72, fontWeight: 600 }}>{content.outro.line}</span>
            <span style={{ fontSize: 34, color: 'var(--on-navy-muted)' }}>{content.outro.team}</span>
          </div>
        )}
      </div>
    </Scene>
  );
}
