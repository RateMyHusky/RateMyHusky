import type { SyntheticEvent } from 'react';

/* Professor photos are hotlinked at full size (up to ~1 MB), so small avatars took
   2+ seconds to appear. backend/photo_thumbs.py saves a small WebP of each one under
   public/photos/, named by a hash of the original URL; this computes the same name.
   The hash is cyrb53 and must stay identical to thumb_name() there. */
function cyrb53(str: string): number {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < str.length; i++) {
    const ch = str.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507);
  h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507);
  h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return 4294967296 * (2097151 & h2) + (h1 >>> 0);
}

export function photoThumb(url: string): string {
  return `/photos/${cyrb53(url).toString(16)}.webp`;
}

/* onError for an <img src={photoThumb(url)}>. A photo added since the thumbnails were
   last made has no file yet, so the first error retries the original URL; if that
   fails too, `fallback` runs (e.g. hide the img and show initials). The flag and
   the fallback's inline styles stay on the element, so where one <img> can show
   different professors, key it (and its fallback) by the photo URL. */
export function thumbOnError(original: string, fallback?: (img: HTMLImageElement) => void) {
  return (e: SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    if (img.dataset.thumbFailed === original) {
      fallback?.(img);
      return;
    }
    img.dataset.thumbFailed = original;
    img.src = original;
  };
}
