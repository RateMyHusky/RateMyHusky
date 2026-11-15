import { SITE_URL } from '../api';

/* The extension's copy of frontend/src/utils/photoThumb.ts, which it can't
   import across packages. Professor photos are hotlinked at full size from
   other universities' sites (up to ~1 MB, 1400px); backend/photo_thumbs.py
   saves a small WebP of each under the site's /photos/, named by a hash of the
   original URL, and this computes the same name. The hash is cyrb53 and must
   stay identical to thumb_name() there and to the frontend's copy —
   photoThumb.test.ts checks the frontend's. */
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

/** The thumbnail's path, as the site serves it. */
export function thumbPath(url: string): string {
  return `/photos/${cyrb53(url).toString(16)}.webp`;
}

/** Absolute, since the popup isn't on ratemyhusky.com. Also keeps the first
 *  request for every photo on our own site rather than a third party's. */
export function photoThumb(url: string): string {
  return `${SITE_URL}${thumbPath(url)}`;
}
