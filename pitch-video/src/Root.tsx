/** Composition: the full video (opening, recorded demo on tablet and laptop, closing). */
import '@fontsource-variable/jost';
import { useEffect, useState } from 'react';
import { Composition, continueRender, delayRender } from 'remotion';
import '../../argos-ui/src/theme.css';
import { Pitch } from './Pitch';
import { FPS, TOTAL_FRAMES } from './timeline';

const SIZE = { width: 1920, height: 1080, fps: FPS };

/** Waits for the Jost font before rendering frames, so no frame uses a fallback font. */
function FontGate({ children }: { children: JSX.Element }) {
  const [handle] = useState(() => delayRender('Loading Jost'));
  useEffect(() => {
    document.fonts.load('400 40px "Jost Variable"').then(() => document.fonts.ready).then(() => continueRender(handle));
  }, [handle]);
  return children;
}

export function Root() {
  return <Composition id="HovisPitch" component={() => <FontGate><Pitch /></FontGate>} durationInFrames={TOTAL_FRAMES} {...SIZE} />;
}
