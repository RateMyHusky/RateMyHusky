// Rules, local state and analytics for the "rate this professor" prompts.
export type RateFrom = 'popup' | 'hero' | 'tab_empty' | 'tab_few' | 'tab_link' | 'direct';
export type PromptTrigger = 'time' | 'scroll' | 'revisit';

export interface PromptState {
  lastShown?: number;
  dismissCount: number;
  lastDismiss?: number;
  lastRated?: number;
  rated: string[];
  lastVisitDay?: string;
}

declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void;
  }
}

export const STORAGE_KEY = 'rmh_rate_prompt';
export const DWELL_MS = 20_000;
export const REVISIT_DWELL_MS = 8_000;
export const MIN_DWELL_MS = 5_000;
export const DAY_MS = 86_400_000;
export const SHOWN_COOLDOWN_MS = DAY_MS;
export const DISMISS_COOLDOWN_MS = 7 * DAY_MS;
export const MAX_DISMISSALS = 3;
export const RATED_COOLDOWN_MS = 21 * DAY_MS;

const FROM_VALUES: RateFrom[] = ['popup', 'hero', 'tab_empty', 'tab_few', 'tab_link', 'direct'];

const defaultState = (): PromptState => ({ dismissCount: 0, rated: [] });

// Returns null when storage is unusable, so callers can show no prompt at all.
export function loadState(storage?: Storage | null): PromptState | null {
  try {
    const store = storage === undefined ? window.localStorage : storage;
    if (!store) return null;
    const raw = store.getItem(STORAGE_KEY);
    if (!raw) return defaultState();
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return defaultState();
      return {
        ...defaultState(),
        ...parsed,
        dismissCount: Number(parsed.dismissCount) || 0,
        rated: Array.isArray(parsed.rated) ? parsed.rated : [],
      };
    } catch {
      return defaultState();
    }
  } catch {
    return null;
  }
}

export function saveState(s: PromptState, storage?: Storage | null): void {
  try {
    const store = storage === undefined ? window.localStorage : storage;
    store?.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    // Storage unavailable or full: prompts just lose their memory.
  }
}

const within = (then: number | undefined, now: number, span: number) =>
  then !== undefined && now - then < span;

export function hasRated(s: PromptState, slug: string): boolean {
  return s.rated.includes(slug);
}

export function canShowPopup(s: PromptState, slug: string, now: number): boolean {
  if (within(s.lastShown, now, SHOWN_COOLDOWN_MS)) return false;
  if (s.dismissCount >= MAX_DISMISSALS) return false;
  if (within(s.lastDismiss, now, DISMISS_COOLDOWN_MS)) return false;
  if (within(s.lastRated, now, RATED_COOLDOWN_MS)) return false;
  return !hasRated(s, slug);
}

export function dayKey(now: number): string {
  const d = new Date(now);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function visitDay(s: PromptState, now: number): { state: PromptState; revisit: boolean } {
  const today = dayKey(now);
  return {
    state: { ...s, lastVisitDay: today },
    revisit: s.lastVisitDay !== undefined && s.lastVisitDay !== today,
  };
}

export const markShown = (s: PromptState, now: number): PromptState => ({ ...s, lastShown: now });

export const markDismissed = (s: PromptState, now: number): PromptState =>
  ({ ...s, dismissCount: s.dismissCount + 1, lastDismiss: now });

export function recordRating(s: PromptState, slug: string | null, now: number): PromptState {
  const rated = slug && !s.rated.includes(slug) ? [...s.rated, slug] : s.rated;
  return { ...s, lastRated: now, rated };
}

export const popupDelay = (revisit: boolean): number => (revisit ? REVISIT_DWELL_MS : DWELL_MS);

export const triggerFor = (signal: 'time' | 'scroll', revisit: boolean): PromptTrigger =>
  revisit ? 'revisit' : signal;

export const parseFrom = (v: string | null): RateFrom =>
  FROM_VALUES.includes(v as RateFrom) ? (v as RateFrom) : 'direct';

export function rateHref(slug: string, from: RateFrom, course?: string | null): string {
  let href = `/rate?professor=${encodeURIComponent(slug)}&from=${encodeURIComponent(from)}`;
  if (course) href += `&course=${encodeURIComponent(course)}`;
  return href;
}

// Only the first path segment: slugs and course codes in the rest of the path never reach GA.
export const analyticsPath = (pathname: string): string => `/${pathname.split('/')[1] ?? ''}`;

function referrerOrigin(): string {
  try {
    return document.referrer ? new URL(document.referrer).origin : '';
  } catch {
    return '';
  }
}

export function track(event: string, params: Record<string, string>): void {
  try {
    if (import.meta.env?.VITE_VERCEL_ENV !== 'production') return;
    if (typeof window.gtag === 'function') {
      window.gtag('event', event, {
        ...params,
        page_location: window.location.origin + analyticsPath(window.location.pathname),
        page_title: 'RateMyHusky',
        page_referrer: referrerOrigin(),
      });
    }
  } catch {
    // Analytics must never break the page.
  }
}

export function markRatedNow(slug: string | null): void {
  const s = loadState();
  if (s) saveState(recordRating(s, slug, Date.now()));
}
