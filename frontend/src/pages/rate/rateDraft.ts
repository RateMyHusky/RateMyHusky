// Unsent /rate answers for this tab, dropped on submit, on "Rate another", or after 2 hours.
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

const STEPS: StepId[] = ['who', 'newProfessor', 'course', 'otherCourse', 'term', 'otherTerm',
  'overall', 'difficulty', 'workload', 'grade', 'comment'];

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
      && d.step !== undefined && STEPS.includes(d.step)
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

export function keepOpened(start: RateStart, draft: RateDraft | null): RateStart {
  return draft?.opened && draft.deviceToken === start.deviceToken ? { ...start, opened: draft.opened } : start;
}
