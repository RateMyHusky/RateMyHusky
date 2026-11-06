// Unsent /rate answers for this tab, dropped on submit, on "Rate another", or after 2 hours.
import { STEP_IDS } from './rateFlow';
import type { Answers, StepId } from './rateFlow';
import type { RateStart } from '../../api/api';

export const RATE_DRAFT_KEY = 'rmh_rate_draft';
export const DRAFT_MAX_AGE_MS = 7_200_000;

export interface RateDraft {
  v: 1;
  savedAt: number;
  step: StepId;
  answers: Answers;
  opened: string | null;
  deviceToken: string | null;
}

export function saveRateDraft(d: Pick<RateDraft, 'step' | 'answers' | 'opened' | 'deviceToken'>, now: number): void {
  try {
    sessionStorage.setItem(RATE_DRAFT_KEY, JSON.stringify({ v: 1, savedAt: now, ...d }));
  } catch { /* storage unavailable: no draft */ }
}

export function clearRateDraft(): void {
  try {
    sessionStorage.removeItem(RATE_DRAFT_KEY);
  } catch { /* storage unavailable */ }
}

export function loadRateDraft(now: number): RateDraft | null {
  try {
    const raw = sessionStorage.getItem(RATE_DRAFT_KEY);
    if (raw === null) return null;
    const d = JSON.parse(raw) as Partial<RateDraft> | null;
    const a = d?.answers;
    if (d && d.v === 1 && typeof d.savedAt === 'number' && now - d.savedAt <= DRAFT_MAX_AGE_MS
      && d.step !== undefined && d.step !== 'thanks' && STEP_IDS.includes(d.step)
      && a && typeof a === 'object' && typeof a.comment === 'string'
      && a.professor && typeof a.professor === 'object') {
      return d as RateDraft;
    }
    sessionStorage.removeItem(RATE_DRAFT_KEY);
    return null;
  } catch {
    return null;
  }
}

// The signed fill start, in server seconds, is the token's first field.
const signedAt = (opened: string) => Number(opened.split('.')[0]);

// The server holds a fill over 2 hours as stale, so a kept start that old gives way to the new one.
export function keepOpened(start: RateStart, draft: Pick<RateDraft, 'opened' | 'deviceToken'> | null): RateStart {
  return draft?.opened && draft.deviceToken === start.deviceToken
    && signedAt(start.opened) - signedAt(draft.opened) <= DRAFT_MAX_AGE_MS / 1000
    ? { ...start, opened: draft.opened } : start;
}
