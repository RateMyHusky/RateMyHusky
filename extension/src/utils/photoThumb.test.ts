import { describe, expect, it } from 'vitest';
import { photoThumb, thumbPath } from './photoThumb';

// The same vectors as backend/tests/test_photo_thumbs.py and the frontend's
// photoThumb.selftest.ts: all three must name a photo's file alike, or the
// popup asks for thumbnails that were saved under another name.
const VECTORS: [string, string][] = [
  ['', 'bdcb81aee8d83'],
  ['a', '1c2ba782c97901'],
  ['https://cssh.northeastern.edu/wp-content/uploads/2020/01/Block-Aaron-414-x-512-px.png', '4fd4a9c944f20'],
  ['https://example.com/José-😀.jpg', '18a7399017e0d'],
];

describe('photoThumb', () => {
  it.each(VECTORS)('names %j like the backend does', (url, hex) => {
    expect(thumbPath(url)).toBe(`/photos/${hex}.webp`);
  });

  it('points at the site, since the popup lives elsewhere', () => {
    expect(photoThumb('a')).toBe('https://ratemyhusky.com/photos/1c2ba782c97901.webp');
  });
});
