/**
 * The whole video: opening logo, the recorded demo on a tablet then a laptop
 * (one title card per role), closing logo. The timeline comes from timeline.ts.
 */
import { AbsoluteFill, Sequence, useCurrentFrame } from 'remotion';
import { SectionTitle } from './demo/SectionTitle';
import { StepView } from './demo/StepView';
import { Caption } from './kit';
import { Intro } from './scenes/Intro';
import { SEGMENTS, STEPS } from './timeline';

/** Light studio backdrop behind the devices. */
function Backdrop() {
  return <AbsoluteFill style={{ background: 'radial-gradient(ellipse 70% 60% at 50% 40%, #ffffff 0%, #e6ebf2 60%, #d5dce7 100%)' }} />;
}

function StepCaption({ index }: { index: number }) {
  const frame = useCurrentFrame();
  return <Caption text={STEPS[index].caption} frame={frame} start={0.25} bottom={26} />;
}

export function Pitch() {
  return (
    <AbsoluteFill style={{ fontFamily: 'var(--font)' }}>
      <Backdrop />
      {SEGMENTS.map((seg, i) => (
        <Sequence key={i} from={seg.from} durationInFrames={seg.frames} name={seg.kind === 'step' ? `step ${seg.index}` : seg.kind}>
          {seg.kind === 'intro' && <Intro frames={seg.frames} />}
          {seg.kind === 'outro' && <Intro frames={seg.frames} closing />}
          {seg.kind === 'section' && <SectionTitle title={seg.title} device={seg.device} frames={seg.frames} />}
          {seg.kind === 'step' && (
            <>
              <StepView index={seg.index} frames={seg.frames} />
              <StepCaption index={seg.index} />
            </>
          )}
        </Sequence>
      ))}
    </AbsoluteFill>
  );
}
