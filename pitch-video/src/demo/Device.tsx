/**
 * Device frames drawn in CSS: a landscape tablet (operator at the workstation)
 * and a laptop (supervisor, AI leader, admin). `screen` gives where the screen
 * sits on the 1920 × 1080 stage, so pointers and zooms can be placed on it.
 */
import type { ReactNode } from 'react';
import type { Step } from '../timeline';

export interface ScreenRect { x: number; y: number; width: number; height: number; scale: number }

// Screen geometry on the stage (stage = 1920 × 1080, caption strip at the bottom).
const TABLET_W = 1240; // displayed width of the 1280 × 800 viewport
const LAPTOP_W = 1300; // displayed width of the 1440 × 900 viewport

export function screenRect(device: Step['device'], viewport: Step['viewport']): ScreenRect {
  const width = device === 'tablet' ? TABLET_W : LAPTOP_W;
  const scale = width / viewport.width;
  const height = viewport.height * scale;
  const top = device === 'tablet' ? 105 : 70;
  return { x: (1920 - width) / 2, y: top, width, height, scale };
}

export function DeviceFrame({ device, screen, children }: { device: Step['device']; screen: ScreenRect; children: ReactNode }) {
  const { x, y, width, height } = screen;
  if (device === 'tablet') {
    const bezel = 34;
    return (
      <>
        <div style={{ position: 'absolute', left: x - bezel, top: y - bezel, width: width + 2 * bezel, height: height + 2 * bezel, borderRadius: 54, background: 'linear-gradient(145deg, #2a2f3a, #10131a)', boxShadow: '0 40px 80px rgba(11, 31, 63, 0.35), inset 0 0 0 2px #3a404c' }}>
          {/* front camera */}
          <div style={{ position: 'absolute', left: bezel / 2 - 5, top: '50%', width: 10, height: 10, marginTop: -5, borderRadius: 5, background: '#3b4252' }} />
        </div>
        <Screen screen={screen} radius={14}>{children}</Screen>
      </>
    );
  }
  const bezel = 22;
  const baseH = 30;
  return (
    <>
      {/* lid */}
      <div style={{ position: 'absolute', left: x - bezel, top: y - bezel, width: width + 2 * bezel, height: height + bezel + 34, borderRadius: '26px 26px 6px 6px', background: 'linear-gradient(180deg, #232833, #12151c)', boxShadow: 'inset 0 0 0 2px #363c48' }}>
        <div style={{ position: 'absolute', left: '50%', top: 8, width: 8, height: 8, marginLeft: -4, borderRadius: 4, background: '#3b4252' }} />
      </div>
      {/* base */}
      <div style={{ position: 'absolute', left: x - bezel - 110, top: y + height + 34, width: width + 2 * bezel + 220, height: baseH, borderRadius: '4px 4px 28px 28px', background: 'linear-gradient(180deg, #cfd5de, #9aa3b0)', boxShadow: '0 30px 60px rgba(11, 31, 63, 0.35)' }}>
        <div style={{ position: 'absolute', left: '50%', top: 0, width: 220, height: 10, marginLeft: -110, borderRadius: '0 0 12px 12px', background: '#aeb6c2' }} />
      </div>
      <Screen screen={screen} radius={4}>{children}</Screen>
    </>
  );
}

function Screen({ screen, radius, children }: { screen: ScreenRect; radius: number; children: ReactNode }) {
  return (
    <div style={{ position: 'absolute', left: screen.x, top: screen.y, width: screen.width, height: screen.height, borderRadius: radius, overflow: 'hidden', background: '#fff' }}>
      {children}
    </div>
  );
}
