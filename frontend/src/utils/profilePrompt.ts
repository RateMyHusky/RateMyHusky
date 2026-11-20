// Rules and local state for the step-by-step student profile popup.
import type { ProfileAnswers } from '../api/api';
import { DISMISS_COOLDOWN_MS, MAX_DISMISSALS, SHOWN_COOLDOWN_MS } from './ratePrompt';

export interface ProfilePromptState {
  lastShown?: number;
  dismissCount: number;
  lastDismiss?: number;
}

export type Step = 0 | 1 | 2 | 3;
// null = not picked yet.
export type YearChoice = number | 'grad' | null;
// Whether the rate popup showed this page view; the profile popup never joins it.
export type RateGate = 'pending' | 'shown' | 'clear';

export const STORAGE_KEY = 'rmh_profile_prompt';
export const RESUME_KEY = 'rmh_profile_resume';
// Older than this, a sign-in is no longer a continuation of the popup.
const RESUME_MAX_AGE_MS = 15 * 60 * 1000;

const defaultState = (): ProfilePromptState => ({ dismissCount: 0 });

// Returns null when storage is unusable, so callers can show no prompt at all.
export function loadState(storage?: Storage | null): ProfilePromptState | null {
  try {
    const store = storage === undefined ? window.localStorage : storage;
    if (!store) return null;
    const raw = store.getItem(STORAGE_KEY);
    if (!raw) return defaultState();
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return defaultState();
      // Known keys only, so old or tampered fields aren't saved back.
      const s: ProfilePromptState = { dismissCount: Number(parsed.dismissCount) || 0 };
      for (const k of ['lastShown', 'lastDismiss'] as const) {
        if (typeof parsed[k] === 'number') s[k] = parsed[k];
      }
      return s;
    } catch {
      return defaultState();
    }
  } catch {
    return null;
  }
}

export function saveState(s: ProfilePromptState, storage?: Storage | null): void {
  try {
    const store = storage === undefined ? window.localStorage : storage;
    store?.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    // Storage unavailable or full: the popup just loses its memory.
  }
}

// A time in the future (a clock that was set ahead) counts as expired, so it can't block the popup for good.
const within = (then: number | undefined, now: number, span: number) =>
  then !== undefined && now >= then && now - then < span;

export function canShowProfilePrompt(s: ProfilePromptState, now: number): boolean {
  if (within(s.lastShown, now, SHOWN_COOLDOWN_MS)) return false;
  if (s.dismissCount >= MAX_DISMISSALS) return false;
  return !within(s.lastDismiss, now, DISMISS_COOLDOWN_MS);
}

export const markShown = (s: ProfilePromptState, now: number): ProfilePromptState => ({ ...s, lastShown: now });

export const markDismissed = (s: ProfilePromptState, now: number): ProfilePromptState =>
  ({ ...s, dismissCount: s.dismissCount + 1, lastDismiss: now });

// Remembers which page the popup was on across a sign-in (same pattern as pendingBookmark.ts).
export function markResume(path: string, storage?: Storage | null): void {
  try {
    const store = storage === undefined ? window.sessionStorage : storage;
    store?.setItem(RESUME_KEY, JSON.stringify({ path, at: Date.now() }));
  } catch {
    // storage blocked: the popup simply doesn't resume
  }
}

// True only for the same path within 15 minutes; removed either way so it applies at most once.
export function takeResume(path: string, now: number, storage?: Storage | null): boolean {
  try {
    const store = storage === undefined ? window.sessionStorage : storage;
    if (!store) return false;
    const raw = store.getItem(RESUME_KEY);
    store.removeItem(RESUME_KEY);
    if (!raw) return false;
    const p = JSON.parse(raw);
    return p.path === path && typeof p.at === 'number' && now - p.at < RESUME_MAX_AGE_MS;
  } catch {
    return false;
  }
}

// Current local year through current + 5.
export function gradYearOptions(now: number): number[] {
  const year = new Date(now).getFullYear();
  return Array.from({ length: 6 }, (_, i) => year + i);
}

export const firstStep = (signedIn: boolean): Step => (signedIn ? 1 : 0);

// A grad student has no programs to pick, so the year step is their last.
export const isLastStep = (step: Step, year: YearChoice): boolean =>
  step === 3 || (step === 1 && year === 'grad');

export function canAdvance(step: Step, year: YearChoice, majors: string[]): boolean {
  if (step === 1) return year !== null;
  if (step === 2) return majors.length > 0;
  return true;
}

export function toAnswers(year: YearChoice, majors: string[], minors: string[]): ProfileAnswers {
  if (year === 'grad' || year === null) return { gradYear: null, majors: [], minors: [] };
  return { gradYear: year, majors, minors };
}
