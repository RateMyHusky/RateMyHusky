import type { PageView } from '../api/api';

// Shorter is a misclick or an instant Back, not interest.
export const MIN_VIEW_SECONDS = 5;

export interface ViewTimer { visibleMs: number; since: number | null }

export function startTimer(now: number, visible: boolean): ViewTimer {
  return { visibleMs: 0, since: visible ? now : null };
}

export function setVisible(t: ViewTimer, visible: boolean, now: number): ViewTimer {
  if (visible) return t.since === null ? { ...t, since: now } : t;
  return t.since === null ? t : { visibleMs: t.visibleMs + (now - t.since), since: null };
}

export function visibleSeconds(t: ViewTimer, now: number): number {
  return Math.floor((t.visibleMs + (t.since === null ? 0 : now - t.since)) / 1000);
}

export function viewToSend(base: Omit<PageView, 'visibleSeconds'>, seconds: number): PageView | null {
  return seconds < MIN_VIEW_SECONDS ? null : { ...base, visibleSeconds: seconds };
}

/* The visible time so far as a view to send. Sending restarts the timer, so time after the student
   comes back becomes the next view; a view too short to send keeps counting. */
export function cutView(t: ViewTimer, now: number, visible: boolean, base: Omit<PageView, 'visibleSeconds'>): { view: PageView | null; timer: ViewTimer } {
  const view = viewToSend(base, visibleSeconds(t, now));
  return { view, timer: view ? startTimer(now, visible) : t };
}
