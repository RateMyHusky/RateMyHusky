import { Composition } from 'remotion';
import { PromoVideo } from './PromoVideo';
import { ExtensionDemo } from './extension/ExtensionDemo';
import { TOTAL_FRAMES as EXTENSION_FRAMES } from './extension/shots';
import { FPS, TOTAL_FRAMES } from './timing';

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="PromoVideo"
      component={PromoVideo}
      durationInFrames={TOTAL_FRAMES}
      fps={FPS}
      width={1920}
      height={1080}
    />
    <Composition
      id="ExtensionDemo"
      component={ExtensionDemo}
      durationInFrames={EXTENSION_FRAMES}
      fps={FPS}
      width={1920}
      height={1080}
    />
  </>
);
