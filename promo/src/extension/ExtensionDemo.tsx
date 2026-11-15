import {
  AbsoluteFill,
  Audio,
  Easing,
  getStaticFiles,
  interpolate,
  OffthreadVideo,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import { TransitionSeries, linearTiming } from '@remotion/transitions';
import { DARK, FONT, MUSIC, RED } from '../branding';
import { Caption } from '../components/Caption';
import { IntroCard } from '../scenes/IntroCard';
import { OutroCard } from '../scenes/OutroCard';
import { driftFade } from '../transitions/driftFade';
import { whipPan } from '../transitions/whipPan';
import {
  CTA,
  HOOK,
  HOOK_FRAMES,
  INTRO_FRAMES,
  OUTRO_FRAMES,
  SHOTS,
  TAGLINE,
  TOTAL_FRAMES,
  TRANSITION_FRAMES,
  type Shot,
} from './shots';

const snap = linearTiming({
  durationInFrames: TRANSITION_FRAMES,
  easing: Easing.bezier(0.65, 0, 0.35, 1),
});

/** A clip with a slow push-in toward the part that matters, so a static
 *  browser frame still feels like it's moving. Full-bleed, like the site
 *  promo's footage, with the caption over it. */
const ShotScene: React.FC<{ shot: Shot; has: boolean }> = ({ shot, has }) => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, shot.frames], [1, 1.06], {
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.quad),
  });
  return (
    <AbsoluteFill style={{ backgroundColor: '#0f0f10' }}>
      <AbsoluteFill style={{ transform: `scale(${scale})`, transformOrigin: shot.focus }}>
        {has ? <OffthreadVideo src={staticFile(shot.file)} muted /> : <Placeholder shot={shot} />}
      </AbsoluteFill>
      <Caption text={shot.caption} />
    </AbsoluteFill>
  );
};

/** The opening line: the problem before the product. Words rise in one at a
 *  time, and "20 tabs" lands in the brand red. */
const HookCard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const words = HOOK.split(' ');
  return (
    <AbsoluteFill
      style={{
        backgroundColor: DARK,
        justifyContent: 'center',
        alignItems: 'center',
        padding: '0 160px',
      }}
    >
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          gap: '0 26px',
          color: '#fff',
          fontFamily: FONT,
          fontWeight: 900,
          fontSize: 96,
          letterSpacing: -2,
          lineHeight: 1.15,
          textAlign: 'center',
        }}
      >
        {words.map((w, i) => {
          const s = spring({ frame: frame - 4 - i * 4, fps, config: { damping: 200 } });
          const red = w.includes('tabs');
          return (
            <span
              key={i}
              style={{
                opacity: s,
                transform: `translateY(${(1 - s) * 40}px)`,
                color: red ? RED : '#fff',
              }}
            >
              {w}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** Stands in for a clip that hasn't been recorded, saying what to film. */
const Placeholder: React.FC<{ shot: Shot }> = ({ shot }) => (
  <AbsoluteFill
    style={{
      justifyContent: 'center',
      alignItems: 'center',
      gap: 24,
      padding: 120,
      fontFamily: FONT,
      color: '#a2a8b4',
      textAlign: 'center',
      border: `3px dashed ${RED}`,
      borderRadius: 22,
    }}
  >
    <div style={{ color: RED, fontWeight: 800, fontSize: 30, letterSpacing: 2 }}>
      RECORD: public/{shot.file}
    </div>
    <div style={{ color: '#fff', fontWeight: 700, fontSize: 48, lineHeight: 1.25 }}>{shot.record}</div>
  </AbsoluteFill>
);

export const ExtensionDemo: React.FC = () => {
  const { width } = useVideoConfig();
  const files = new Set(getStaticFiles().map((f) => f.name));
  const hasMusic = files.has(MUSIC);

  return (
    <AbsoluteFill style={{ backgroundColor: DARK }}>
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={HOOK_FRAMES}>
          <HookCard />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={whipPan({ width })} timing={snap} />
        <TransitionSeries.Sequence durationInFrames={INTRO_FRAMES}>
          <IntroCard tagline={TAGLINE} />
        </TransitionSeries.Sequence>
        {SHOTS.flatMap((shot, i) => [
          i === 0 ? (
            <TransitionSeries.Transition key={`${shot.id}-in`} presentation={driftFade()} timing={snap} />
          ) : (
            <TransitionSeries.Transition key={`${shot.id}-in`} presentation={whipPan({ width })} timing={snap} />
          ),
          <TransitionSeries.Sequence key={shot.id} durationInFrames={shot.frames}>
            <ShotScene shot={shot} has={files.has(shot.file)} />
          </TransitionSeries.Sequence>,
        ])}
        <TransitionSeries.Transition presentation={driftFade()} timing={snap} />
        <TransitionSeries.Sequence durationInFrames={OUTRO_FRAMES}>
          <OutroCard cta={CTA} />
        </TransitionSeries.Sequence>
      </TransitionSeries>
      {/* The site promo's track, when it's on this machine (public/music is
          gitignored). Without it the video renders silent. At 0.8: the track
          is mastered to 0 dB, which clips on phone speakers at full volume. */}
      {hasMusic && (
        <Audio
          src={staticFile(MUSIC)}
          volume={(f) =>
            interpolate(f, [0, 24, TOTAL_FRAMES - 60, TOTAL_FRAMES - 6], [0, 0.8, 0.8, 0], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            })
          }
        />
      )}
    </AbsoluteFill>
  );
};
