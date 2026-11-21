// Rules and local state for the step-by-step student profile popup.
import type { ProfileAnswers } from '../api/api';
import { DAY_MS, SHOWN_COOLDOWN_MS } from './ratePrompt';

export interface ProfilePromptState {
  lastShown?: number;
  dismissCount: number;
  lastDismiss?: number;
}

// 1-3 are the questions; 4 asks a signed-out student to sign in so the answers can be saved.
export type Step = 1 | 2 | 3 | 4;
// null = not picked yet.
export type YearChoice = number | 'grad' | null;
// Whether the rate popup showed this page view; the profile popup never joins it.
export type RateGate = 'pending' | 'shown' | 'clear';

// Answers carried through a sign-in, so they can be saved once it finishes.
export interface ResumeAnswers {
  year: YearChoice;
  majors: string[];
  minors: string[];
}

export const STORAGE_KEY = 'rmh_profile_prompt';
// Visible time before the popup opens, or after a scroll to the reviews or course table.
export const PROFILE_DWELL_MS = 10_000;
export const PROFILE_SCROLL_DWELL_MS = 3_000;
const DISMISS_COOLDOWN_MS = 3 * DAY_MS;
// Three skips pause the popup for about a semester; after that it gets three more.
const MAX_DISMISSALS = 3;
const ROUND_PAUSE_MS = 90 * DAY_MS;
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
  if (s.dismissCount >= MAX_DISMISSALS) return !within(s.lastDismiss, now, ROUND_PAUSE_MS);
  return !within(s.lastDismiss, now, DISMISS_COOLDOWN_MS);
}

export const markShown = (s: ProfilePromptState, now: number): ProfilePromptState => ({ ...s, lastShown: now });

// A skip after a full round's pause starts the next round.
export const markDismissed = (s: ProfilePromptState, now: number): ProfilePromptState =>
  ({ ...s, dismissCount: (s.dismissCount >= MAX_DISMISSALS ? 0 : s.dismissCount) + 1, lastDismiss: now });

// Remembers the page and the answers across a sign-in (same pattern as pendingBookmark.ts).
export function markResume(path: string, answers: ResumeAnswers, storage?: Storage | null): void {
  try {
    const store = storage === undefined ? window.sessionStorage : storage;
    store?.setItem(RESUME_KEY, JSON.stringify({ path, at: Date.now(), answers }));
  } catch {
    // storage blocked: the popup simply doesn't resume
  }
}

const isNames = (v: unknown): v is string[] => Array.isArray(v) && v.every((n) => typeof n === 'string');

// The answers, only for the same path within 15 minutes; removed either way so it applies at most once.
export function takeResume(path: string, now: number, storage?: Storage | null): ResumeAnswers | null {
  try {
    const store = storage === undefined ? window.sessionStorage : storage;
    if (!store) return null;
    const raw = store.getItem(RESUME_KEY);
    store.removeItem(RESUME_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw);
    if (p.path !== path || typeof p.at !== 'number' || now - p.at >= RESUME_MAX_AGE_MS) return null;
    const a = p.answers;
    if (!a || !(a.year === 'grad' || typeof a.year === 'number') || !isNames(a.majors) || !isNames(a.minors)) return null;
    return { year: a.year, majors: a.majors, minors: a.minors };
  } catch {
    return null;
  }
}

// Current local year through current + 5, capped at the UTC year + 5 the backend accepts
// (ahead of UTC on Jan 1, the local year is already the next one).
export function gradYearOptions(now: number): number[] {
  const d = new Date(now);
  const year = d.getFullYear();
  return Array.from({ length: 6 }, (_, i) => year + i).filter((y) => y <= d.getUTCFullYear() + 5);
}

// A grad student has no programs to pick, so the year step is their last question.
export const isLastQuestion = (step: Step, year: YearChoice): boolean =>
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
