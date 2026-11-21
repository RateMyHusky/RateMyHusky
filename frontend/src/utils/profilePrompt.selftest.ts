// Runnable self-check for profilePrompt (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/profilePrompt.selftest.ts
// Prints PASS/FAIL per check and exits non-zero on any failure.
import { isDeepStrictEqual } from 'node:util';
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { DAY_MS } from './ratePrompt';
import {
  RESUME_KEY, STORAGE_KEY,
  canAdvance, canShowProfilePrompt, gradYearOptions, isLastQuestion, loadState, markDismissed,
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
  check('dismiss blocks 3 days', !canShowProfilePrompt(markDismissed(fresh, T), T + 3 * DAY_MS - 1)
    && canShowProfilePrompt(markDismissed(fresh, T), T + 3 * DAY_MS));
  const third = markDismissed(markDismissed(markDismissed(fresh, T), T), T);
  check('three dismissals pause 90 days', third.dismissCount === 3
    && !canShowProfilePrompt(third, T + 89 * DAY_MS) && canShowProfilePrompt(third, T + 90 * DAY_MS));
  check('a skip after the pause starts a new round', (() => { const s = markDismissed(third, T + 90 * DAY_MS);
    return s.dismissCount === 1 && !canShowProfilePrompt(s, T + 92 * DAY_MS) && canShowProfilePrompt(s, T + 93 * DAY_MS); })());
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
  check('grad finishes at step 1', isLastQuestion(1, 'grad') && !isLastQuestion(1, 2028) && isLastQuestion(3, 2028));
  check('advance', !canAdvance(1, null, []) && canAdvance(1, 'grad', []) && !canAdvance(2, 2028, []) && canAdvance(2, 2028, ['other']));
  check('grad answers drop programs', isDeepStrictEqual(toAnswers('grad', ['x'], ['y']), { gradYear: null, majors: [], minors: [] }));
  const answers = { year: 2028, majors: ['Computer Science, BSCS'], minors: [] };
  check('resume other path is null and removes it', (() => { const s = fakeSession(); markResume('/professors/a', answers, s);
    return takeResume('/professors/b', Date.now(), s) === null && takeResume('/professors/a', Date.now(), s) === null; })());
  check('resume same path once, with the answers', (() => { const s = fakeSession(); markResume('/courses/cs2500', answers, s);
    return isDeepStrictEqual(takeResume('/courses/cs2500', Date.now(), s), answers) && takeResume('/courses/cs2500', Date.now(), s) === null; })());
  check('resume keeps a grad student', (() => { const s = fakeSession(); const grad = { year: 'grad' as const, majors: [], minors: [] };
    markResume('/courses/cs2500', grad, s); return isDeepStrictEqual(takeResume('/courses/cs2500', Date.now(), s), grad); })());
  check('resume expires', (() => { const s = fakeSession(); markResume('/courses/cs2500', answers, s);
    return takeResume('/courses/cs2500', Date.now() + 16 * 60_000, s) === null; })());
  check('resume without answers (older marker) is null', takeResume('/courses/cs2500', Date.now(),
    fakeStorage(JSON.stringify({ path: '/courses/cs2500', at: Date.now() }), RESUME_KEY)) === null);
  check('resume with tampered answers is null', takeResume('/courses/cs2500', Date.now(),
    fakeStorage(JSON.stringify({ path: '/courses/cs2500', at: Date.now(), answers: { year: '2028', majors: [1], minors: [] } }), RESUME_KEY)) === null);

  console.log(fails.length ? `${fails.length} FAIL(s): ` + fails.join(', ') : 'ALL PASS');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
