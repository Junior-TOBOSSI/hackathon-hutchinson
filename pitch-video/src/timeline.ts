/**
 * Builds the video timeline from the recorded demo (public/capture/steps.json):
 *   opening logo → for each role: a title card, then its steps → closing logo.
 * Step durations come from `hold` in capture/record.mjs and are stretched or squeezed
 * together so the whole video lasts TARGET_SECONDS (the pitch slot).
 */
import steps from '../public/capture/steps.json';

export const FPS = 30;
export const TARGET_SECONDS = 300; // 5 min pitch
export const INTRO_SECONDS = 12;
export const OUTRO_SECONDS = 12;
export const SECTION_SECONDS = 4;

export interface Box { x: number; y: number; width: number; height: number }
export interface Step {
  image: string;
  section: string | null;
  device: 'tablet' | 'laptop';
  viewport: { width: number; height: number };
  hold: number;
  caption: string;
  target: { x: number; y: number } | null;
  zoom: Box | null;
}

export const STEPS = steps as Step[];

export type Segment =
  | { kind: 'intro' | 'outro'; from: number; frames: number }
  | { kind: 'section'; from: number; frames: number; title: string; device: Step['device'] }
  | { kind: 'step'; from: number; frames: number; index: number };

/** A segment before it is placed on the timeline (no `from` yet); distributes over the union. */
type SegmentWithoutStart = Segment extends infer S ? (S extends Segment ? Omit<S, 'from'> : never) : never;

const sections = STEPS.filter((s) => s.section).length;
const fixed = INTRO_SECONDS + OUTRO_SECONDS + sections * SECTION_SECONDS;
const totalHold = STEPS.reduce((sum, s) => sum + s.hold, 0);
/** Factor applied to every `hold` so the video fits the pitch slot exactly. */
export const HOLD_SCALE = Math.max(0.5, (TARGET_SECONDS - fixed) / totalHold);

export const SEGMENTS: Segment[] = (() => {
  const out: Segment[] = [];
  let at = 0;
  const push = (seg: SegmentWithoutStart) => {
    out.push({ ...seg, from: at } as Segment);
    at += seg.frames;
  };
  push({ kind: 'intro', frames: INTRO_SECONDS * FPS });
  STEPS.forEach((step, index) => {
    if (step.section) push({ kind: 'section', frames: SECTION_SECONDS * FPS, title: step.section, device: step.device });
    push({ kind: 'step', frames: Math.round(step.hold * HOLD_SCALE * FPS), index });
  });
  push({ kind: 'outro', frames: OUTRO_SECONDS * FPS });
  return out;
})();

export const TOTAL_FRAMES = SEGMENTS.reduce((sum, s) => sum + s.frames, 0);
