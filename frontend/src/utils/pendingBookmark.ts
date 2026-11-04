// A bookmark tapped while signed out, kept across sign-in so it can be saved once the
// student is back. sessionStorage survives the mobile full-page Google redirect (same tab)
// and the desktop popup (this window never leaves), and is gone when the tab closes.

const KEY = 'pending_bookmark';
// Older than this, the tap is stale: a sign-in much later shouldn't save something unasked.
const MAX_AGE_MS = 15 * 60 * 1000;

export interface PendingBookmark {
  itemType: 'professor' | 'course';
  itemKey: string;
  label: string;
}

export function savePendingBookmark(pending: PendingBookmark): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ ...pending, at: Date.now() }));
  } catch {
    // storage blocked: the student taps again after signing in, as before
  }
}

export function clearPendingBookmark(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* storage blocked */
  }
}

/** The pending bookmark if it is fresh, removed either way so it is applied at most once. */
export function takePendingBookmark(): PendingBookmark | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    if (!raw) return null;
    const p = JSON.parse(raw);
    const fresh = typeof p.at === 'number' && Date.now() - p.at < MAX_AGE_MS;
    const valid = (p.itemType === 'professor' || p.itemType === 'course') && typeof p.itemKey === 'string' && p.itemKey;
    return fresh && valid ? { itemType: p.itemType, itemKey: p.itemKey, label: String(p.label || '') } : null;
  } catch {
    return null;
  }
}
