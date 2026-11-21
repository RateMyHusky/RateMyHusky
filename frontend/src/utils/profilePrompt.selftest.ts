// Runnable self-check for profilePrompt (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/profilePrompt.selftest.ts
// Prints PASS/FAIL per check and exits non-zero on any failure.
import { isDeepStrictEqual } from 'node:util';
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { DAY_MS } from './ratePrompt';
import {
  RESUME_KEY, STORAGE_KEY,
  canAdvance, canShowProfilePrompt, firstStep, gradYearOptions, isLastStep, loadState, markDismissed,
  markResume, markShown, takeResume, toAnswers,
  type ProfilePromptState,
} from './profilePrompt';

function fakeStorage(initial?: string, key: string = STORAGE_KEY): Storage {
  const m = new Map<string, string>();
  if (initial !== undefined) m.set(key, initial);
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => { m.set(k, v); },
    removeItem: (k: string) => { m.delete(k); },
  } as unknown as Storage;
}

const fakeSession = () => fakeStorage(undefined, RESUME_KEY);

const throwingStorage = {
  getItem: () => { throw new Error('denied'); },
  setItem: () => { throw new Error('denied'); },
  removeItem: () => { throw new Error('denied'); },
} as unknown as Storage;

function selftest(): number {
  const fails: string[] = [];
  const check = (label: string, cond: boolean) => {
    if (!cond) fails.push(label);
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  };
  const T = new Date(2026, 10, 20, 12).getTime();
  const fresh: ProfilePromptState = { dismissCount: 0 };

  check('fresh can show', canShowProfilePrompt(loadState(fakeStorage())!, T));
  check('shown blocks a day', !canShowProfilePrompt(markShown(fresh, T), T + DAY_MS - 1) && canShowProfilePrompt(markShown(fresh, T), T + DAY_MS));
  check('dismiss blocks a week', !canShowProfilePrompt(markDismissed(fresh, T), T + 7 * DAY_MS - 1));
  check('three dismissals end it', !canShowProfilePrompt({ dismissCount: 3 }, T + 365 * DAY_MS));
  check('future clock does not block', canShowProfilePrompt({ dismissCount: 0, lastShown: T + DAY_MS * 30 }, T));
  check('throwing storage', loadState(throwingStorage) === null);
  check('tampered fields dropped', isDeepStrictEqual(loadState(fakeStorage('{"dismissCount":"x","lastShown":"y","junk":1}')), { dismissCount: 0 }));
  check('years', isDeepStrictEqual(gradYearOptions(T), [2026, 2027, 2028, 2029, 2030, 2031]));
  // The backend accepts UTC year - 1 through UTC year + 5.
  const withTz = <R,>(tz: string, fn: () => R): R => {
    const saved = process.env.TZ;
    process.env.TZ = tz;
    try { return fn(); } finally { if (saved === undefined) delete process.env.TZ; else process.env.TZ = saved; }
  };
  check('years ahead of UTC on Jan 1 stay in range', isDeepStrictEqual(
    withTz('Asia/Tokyo', () => gradYearOptions(Date.parse('2026-12-31T15:30:00Z'))), [2027, 2028, 2029, 2030, 2031]));
  check('years behind UTC on Dec 31 keep the local year', isDeepStrictEqual(
    withTz('America/New_York', () => gradYearOptions(Date.parse('2027-01-01T03:00:00Z'))), [2026, 2027, 2028, 2029, 2030, 2031]));
  check('first step', firstStep(false) === 0 && firstStep(true) === 1);
  check('grad finishes at step 1', isLastStep(1, 'grad') && !isLastStep(1, 2028) && isLastStep(3, 2028));
  check('advance', !canAdvance(1, null, []) && canAdvance(1, 'grad', []) && !canAdvance(2, 2028, []) && canAdvance(2, 2028, ['other']));
  check('grad answers drop programs', isDeepStrictEqual(toAnswers('grad', ['x'], ['y']), { gradYear: null, majors: [], minors: [] }));
  check('resume other path is false and removes it', (() => { const s = fakeSession(); markResume('/professors/a', s);
    return !takeResume('/professors/b', Date.now(), s) && !takeResume('/professors/a', Date.now(), s); })());
  check('resume same path once', (() => { const s = fakeSession(); markResume('/courses/cs2500', s);
    return takeResume('/courses/cs2500', Date.now(), s) && !takeResume('/courses/cs2500', Date.now(), s); })());
  check('resume expires', (() => { const s = fakeSession(); markResume('/courses/cs2500', s);
    return !takeResume('/courses/cs2500', Date.now() + 16 * 60_000, s); })());

  console.log(fails.length ? `${fails.length} FAIL(s): ` + fails.join(', ') : 'ALL PASS');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
