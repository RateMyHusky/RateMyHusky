import type { PageView } from '../api/api';

export const MIN_VIEW_SECONDS = 2;

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

/* Forwards the first non-null view and ignores the rest. */
export function makeSender(send: (v: PageView) => void): (v: PageView | null) => void {
  let sent = false;
  return (v) => {
    if (sent || !v) return;
    sent = true;
    send(v);
  };
}
