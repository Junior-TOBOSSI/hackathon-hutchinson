/**
 * One recorded step, shown on its device. Within the step (times in seconds):
 *   0 → 0.35          cross-fade from the previous screenshot (same device)
 *   zoom              camera zooms on `step.zoom` early, and zooms back out before the end
 *   end-1.7 → end-0.7 pointer travels to `step.target`
 *   end-0.55          click / tap, with a ripple; the next step shows the result
 */
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { progress, s } from '../kit';
import { STEPS, type Step } from '../timeline';
import { DeviceFrame, screenRect, type ScreenRect } from './Device';
import { Fingertip, MouseArrow, Ripple } from './Pointer';

const toStage = (screen: ScreenRect, p: { x: number; y: number }) => ({ x: screen.x + p.x * screen.scale, y: screen.y + p.y * screen.scale });

/** Where the pointer rests at the start of a step: where the previous step clicked. */
function restingPoint(index: number, screen: ScreenRect) {
  const prev = STEPS[index - 1];
  if (prev && prev.device === STEPS[index].device && prev.target) return toStage(screen, prev.target);
  return { x: screen.x + screen.width * 0.62, y: screen.y + screen.height * 0.7 };
}

function zoomTransform(step: Step, screen: ScreenRect, frame: number, frames: number) {
  if (!step.zoom) return undefined;
  const z = step.zoom;
  const c = toStage(screen, { x: z.x + z.width / 2, y: z.y + z.height / 2 });
  const factor = Math.min(1.9, Math.max(1.2, Math.min((0.62 * 1920) / (z.width * screen.scale), (0.72 * 1080) / (z.height * screen.scale))));
  const end = frames / s(1);
  const p = Math.min(progress(frame, 0.8, 1.2), 1 - progress(frame, end - 1.6, 1.2));
  return {
    transformOrigin: `${c.x}px ${c.y}px`,
    transform: `translate(${(960 - c.x) * p}px, ${(500 - c.y) * p}px) scale(${1 + (factor - 1) * p})`,
  };
}

export function StepView({ index, frames }: { index: number; frames: number }) {
  const frame = useCurrentFrame();
  const step = STEPS[index];
  const prev = STEPS[index - 1];
  const screen = screenRect(step.device, step.viewport);
  const end = frames / s(1);

  // Cross-fade from the previous screenshot when the device does not change.
  const showPrev = prev && prev.device === step.device && !step.section;
  const fadeIn = showPrev ? progress(frame, 0, 0.35) : 1;

  // Pointer path.
  const rest = restingPoint(index, screen);
  const goal = step.target ? toStage(screen, step.target) : rest;
  const travel = interpolate(frame, [s(end - 1.7), s(end - 0.7)], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic) });
  const px = rest.x + (goal.x - rest.x) * travel;
  const py = rest.y + (goal.y - rest.y) * travel;
  const clickAt = end - 0.55;
  const pressed = !!step.target && frame >= s(clickAt) && frame < s(clickAt + 0.18);
  const ripple = step.target ? interpolate(frame, [s(clickAt), s(clickAt + 0.6)], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }) : 0;
  // The fingertip only appears for a tap (tablet).
  const fingerOpacity = step.target ? interpolate(frame, [s(end - 1.4), s(end - 1.0), s(end - 0.3), s(end - 0.1)], [0, 1, 1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }) : 0;

  return (
    <AbsoluteFill style={zoomTransform(step, screen, frame, frames)}>
      <DeviceFrame device={step.device} screen={screen}>
        {showPrev && <Img src={staticFile(`capture/${prev.image}`)} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} />}
        <Img src={staticFile(`capture/${step.image}`)} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: fadeIn }} />
      </DeviceFrame>
      {step.target && <Ripple x={goal.x} y={goal.y} t={ripple} />}
      {step.device === 'laptop'
        ? <MouseArrow x={px} y={py} pressed={pressed} />
        : <Fingertip x={px} y={py} opacity={fingerOpacity} pressed={pressed} />}
    </AbsoluteFill>
  );
}
