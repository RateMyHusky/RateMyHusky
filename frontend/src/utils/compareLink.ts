// The Compare page's slots, one URL param each: /compare?a=slug&b=slug&c=slug&d=slug.
// Shared so every link into Compare fills the same slots the page reads.
export const COMPARE_SLOT_KEYS = ['a', 'b', 'c', 'd'] as const;
export const COMPARE_MAX = COMPARE_SLOT_KEYS.length;

/** A /compare link with these professors in slots A, B, ... (extras beyond the last slot dropped). */
export function compareHref(slugs: string[]): string {
  const params = new URLSearchParams();
  slugs.slice(0, COMPARE_MAX).forEach((slug, i) => params.set(COMPARE_SLOT_KEYS[i], slug));
  return `/compare?${params.toString()}`;
}
