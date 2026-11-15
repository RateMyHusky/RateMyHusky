import {
  AbsoluteFill,
  Img,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import { FONT, RED, TAGLINE } from '../branding';

export const IntroCard: React.FC<{ tagline?: string }> = ({ tagline = TAGLINE }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const logoS = spring({ frame, fps, config: { damping: 12, mass: 0.6 } });
  const wordS = spring({ frame: frame - 10, fps, config: { damping: 200 } });
  const textS = spring({ frame: frame - 20, fps, config: { damping: 200 } });
  return (
    <AbsoluteFill
      style={{
        backgroundColor: RED,
        justifyContent: 'center',
        alignItems: 'center',
        gap: 36,
      }}
    >
      <div
        style={{
          background: '#fff',
          borderRadius: 36,
          padding: 24,
          boxShadow: '0 20px 60px rgba(0,0,0,.35)',
          transform: `scale(${logoS})`,
        }}
      >
        <Img
          src={staticFile('logo.png')}
          style={{ width: 150, height: 150, display: 'block' }}
        />
      </div>
      <div
        style={{
          opacity: wordS,
          transform: `translateY(${(1 - wordS) * 30}px)`,
          color: '#fff',
          fontFamily: FONT,
          fontWeight: 900,
          fontSize: 100,
          letterSpacing: -2,
        }}
      >
        RateMyHusky
      </div>
      <div
        style={{
          opacity: textS * 0.95,
          transform: `translateY(${(1 - textS) * 30}px)`,
          color: '#fff',
          fontFamily: FONT,
          fontWeight: 700,
          fontSize: 44,
          letterSpacing: -1,
          textAlign: 'center',
          padding: '0 120px',
        }}
      >
        {tagline}
      </div>
    </AbsoluteFill>
  );
};
