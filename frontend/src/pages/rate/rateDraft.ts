// Unsent /rate answers for this tab, dropped on submit, on "Rate another", on Sign Out in this tab,
// after 2 hours, or when another account signs in, since an update draft holds the earlier rating's
// answers.
import { STEP_IDS } from './rateFlow';
import type { Answers, StepId } from './rateFlow';
import type { RateStart } from '../../api/api';

export const RATE_DRAFT_KEY = 'rmh_rate_draft';
export const DRAFT_MAX_AGE_MS = 7_200_000;
export const RESUME_MAX_AGE_MS = 600_000;

export interface RateDraft {
  v: 1;
  savedAt: number;
  owner: string;
  step: StepId;
  answers: Answers;
  opened: string | null;
  deviceToken: string | null;
}

export function saveRateDraft(d: Pick<RateDraft, 'owner' | 'step' | 'answers' | 'opened' | 'deviceToken'>, now: number): void {
  try {
    sessionStorage.setItem(RATE_DRAFT_KEY, JSON.stringify({ v: 1, savedAt: now, ...d }));
  } catch { /* storage unavailable: no draft */ }
}

export function clearRateDraft(): void {
  try {
    sessionStorage.removeItem(RATE_DRAFT_KEY);
  } catch { /* storage unavailable */ }
}

// One-shot: set when the session ends while the form is open, so the form that remounts after the
// same account signs back in keeps the draft even when the URL no longer matches it. It lapses
// after 10 minutes, so a later sign-in and an unrelated rate link aren't overridden by it.
const RESUME_KEY = 'rate_resume_draft';

export function markResumeDraft(owner: string, now: number): void {
  try {
    sessionStorage.setItem(RESUME_KEY, JSON.stringify({ owner, at: now }));
  } catch { /* storage unavailable: the draft restores only for a matching link */ }
}

export function takeResumeDraft(owner: string, now: number): boolean {
  try {
    const raw = sessionStorage.getItem(RESUME_KEY);
    sessionStorage.removeItem(RESUME_KEY);
    const r = raw === null ? null : JSON.parse(raw) as { owner?: unknown; at?: unknown } | null;
    return !!r && r.owner === owner && typeof r.at === 'number' && now - r.at <= RESUME_MAX_AGE_MS;
  } catch {
    return false;
  }
}

export function loadRateDraft(now: number, owner: string): RateDraft | null {
  try {
    const raw = sessionStorage.getItem(RATE_DRAFT_KEY);
    if (raw === null) return null;
    const d = JSON.parse(raw) as Partial<RateDraft> | null;
    const a = d?.answers;
    if (d && d.v === 1 && d.owner === owner && typeof d.savedAt === 'number' && now - d.savedAt <= DRAFT_MAX_AGE_MS
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
