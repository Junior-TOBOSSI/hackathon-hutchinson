/** Title card introducing a role (and its device) before its part of the demo. */
import { useCurrentFrame } from 'remotion';
import { Icon, ICONS } from '../../../argos-ui/src/components/ui';
import { enter, Scene } from '../kit';
import type { Step } from '../timeline';

export function SectionTitle({ title, device, frames }: { title: string; device: Step['device']; frames: number }) {
  const frame = useCurrentFrame();
  return (
    <Scene frames={frames} dark>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 34 }}>
        <div style={{ width: 120, height: 120, borderRadius: 34, border: '3px solid var(--navy-line)', display: 'flex', alignItems: 'center', justifyContent: 'center', ...enter(frame, 0.2) }}>
          <Icon d={device === 'tablet' ? ICONS.badge : ICONS.monitor} size={64} color="#fff" stroke={1.8} />
        </div>
        <div style={{ width: 64, height: 6, borderRadius: 3, background: 'var(--red)', ...enter(frame, 0.35) }} />
        <span style={{ fontSize: 76, fontWeight: 500, letterSpacing: '0.01em', ...enter(frame, 0.45) }}>{title}</span>
        <span style={{ fontSize: 30, letterSpacing: '0.24em', textTransform: 'uppercase', color: 'var(--on-navy-muted)', ...enter(frame, 0.7) }}>
          {device === 'tablet' ? 'Tablette' : device === 'tv' ? 'Écran TV' : 'Ordinateur'}
        </span>
      </div>
    </Scene>
  );
}
