/**
 * Shared building blocks for every scene: easing helpers, the scene frame
 * (background + fade in/out + title) and a few branded primitives.
 * Brand colours come from argos-ui/src/theme.css (CSS variables), so the video
 * always matches the HOVIS interface.
 */
import type { CSSProperties, ReactNode } from 'react';
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { FPS } from './timeline';

/** Seconds to frames, so scene code reads in seconds. */
export const s = (seconds: number) => Math.round(seconds * FPS);

/** 0 → 1 between `start` and `start + duration` (in seconds), eased, clamped. */
export function progress(frame: number, start: number, duration = 0.6) {
  return interpolate(frame, [s(start), s(start + duration)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });
}

/** Fade + slight rise, for elements entering at `start` seconds. */
export function enter(frame: number, start: number, distance = 24): CSSProperties {
  const p = progress(frame, start);
  return { opacity: p, transform: `translateY(${(1 - p) * distance}px)` };
}

/** Springy 0 → 1 pop, for icons and badges. */
export function usePop(start: number) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - s(start), fps, config: { damping: 14, mass: 0.6 } });
}

/** Common scene frame: background, fade in/out, optional title at the top left. */
export function Scene({ frames, dark = false, title, children }: { frames: number; dark?: boolean; title?: string; children: ReactNode }) {
  const frame = useCurrentFrame();
  const fade = Math.min(
    interpolate(frame, [0, s(0.5)], [0, 1], { extrapolateRight: 'clamp' }),
    interpolate(frame, [frames - s(0.5), frames], [1, 0], { extrapolateLeft: 'clamp' }),
  );
  return (
    <AbsoluteFill
      style={{
        background: dark ? 'var(--navy)' : 'var(--app-bg)',
        color: dark ? '#fff' : 'var(--ink)',
        fontFamily: 'var(--font)',
        opacity: fade,
      }}
    >
      {title && (
        <div style={{ position: 'absolute', left: 120, top: 90, ...enter(frame, 0.2) }}>
          <div style={{ width: 64, height: 6, borderRadius: 3, background: 'var(--red)', marginBottom: 22 }} />
          <h1 style={{ margin: 0, fontSize: 56, fontWeight: 600, letterSpacing: '0.01em' }}>{title}</h1>
        </div>
      )}
      {children}
    </AbsoluteFill>
  );
}

/** White rounded card, same look as the interface cards. */
export function Card({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div style={{ background: '#fff', borderRadius: 28, boxShadow: '0 0 0 1px var(--line), 0 10px 30px rgba(11, 31, 63, 0.08)', padding: 36, ...style }}>
      {children}
    </div>
  );
}

/** Caption strip at the bottom, to help the jury follow while the speaker talks. */
export function Caption({ text, frame, start, bottom = 56, onDark = false }: { text: string; frame: number; start: number; bottom?: number; onDark?: boolean }) {
  return (
    <div style={{ position: 'absolute', left: 0, right: 0, bottom, display: 'flex', justifyContent: 'center', ...enter(frame, start, 16) }}>
      <span style={{ background: onDark ? '#fff' : 'var(--navy)', color: onDark ? 'var(--navy)' : '#fff', padding: '12px 30px', borderRadius: 16, fontSize: 30, fontWeight: 500, boxShadow: '0 12px 30px rgba(11, 31, 63, 0.3)' }}>
        {text}
      </span>
    </div>
  );
}
