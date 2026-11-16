import {
  AbsoluteFill,
  Img,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import { CTA, DARK, FONT, RED } from '../branding';

export const OutroCard: React.FC<{ cta?: string }> = ({ cta = CTA }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const logoS = spring({ frame, fps, config: { damping: 200 } });
  const urlS = spring({ frame: frame - 10, fps, config: { damping: 14, mass: 0.7 } });
  const ctaS = spring({ frame: frame - 24, fps, config: { damping: 200 } });
  return (
    <AbsoluteFill
      style={{
        backgroundColor: DARK,
        justifyContent: 'center',
        alignItems: 'center',
        gap: 36,
      }}
    >
      <div
        style={{
          background: '#fff',
          borderRadius: 24,
          padding: 16,
          opacity: logoS,
        }}
      >
        <Img
          src={staticFile('logo.png')}
          style={{ width: 96, height: 96, display: 'block' }}
        />
      </div>
      <div
        style={{
          color: '#fff',
          fontFamily: FONT,
          fontWeight: 900,
          fontSize: 96,
          letterSpacing: -2,
          transform: `scale(${urlS})`,
        }}
      >
        ratemyhusky.com
      </div>
      <div
        style={{
          opacity: ctaS,
          transform: `translateY(${(1 - ctaS) * 24}px)`,
          background: RED,
          color: '#fff',
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 40,
          padding: '12px 34px',
          borderRadius: 999,
        }}
      >
        {cta}
      </div>
    </AbsoluteFill>
  );
};
