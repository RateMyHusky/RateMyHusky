import { useState, type CSSProperties, type ReactNode } from 'react';
import { safeHttpUrl } from '../api';
import { photoThumb } from '../utils/photoThumb';

/** A professor's photo: the site's small thumbnail first, the original if no
 *  thumbnail has been made yet (a photo added since the last run), and the
 *  fallback if that's dead or blocks hotlinking too — never a broken-image
 *  icon. Callers key it by the URL, so a new professor starts over at the
 *  thumbnail. */
export default function Photo({
  url,
  className,
  style,
  fallback,
}: {
  url: string | null | undefined;
  className: string;
  style?: CSSProperties;
  fallback: ReactNode;
}) {
  const original = safeHttpUrl(url);
  const [stage, setStage] = useState<'thumb' | 'original' | 'failed'>('thumb');

  if (!original || stage === 'failed') return <>{fallback}</>;
  return (
    <img
      className={className}
      src={stage === 'thumb' ? photoThumb(original) : original}
      alt=""
      loading="lazy"
      style={style}
      onError={() => setStage(stage === 'thumb' ? 'original' : 'failed')}
    />
  );
}
