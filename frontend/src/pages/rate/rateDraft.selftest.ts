// Runnable self-check for rateDraft (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/pages/rate/rateDraft.selftest.ts
// Prints PASS/FAIL per check and exits non-zero on any failure.
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { RATE_DRAFT_KEY, DRAFT_MAX_AGE_MS, saveRateDraft, loadRateDraft, clearRateDraft, keepOpened } from './rateDraft';
import type { RateDraft } from './rateDraft';
import type { RateStart, RatedCourse } from '../../api/api';
import { installStorage } from '../../utils/selftestStorage';

function selftest(): number {
  const fails: string[] = [];
  const check = (label: string, cond: boolean) => {
    if (!cond) fails.push(label);
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  };

  const now = 1_000_000_000;
  const store = installStorage();
  const updating: RatedCourse = {
    code: 'CS 2500', name: 'Fundamentals', pending: false, term: 'Fall 2025',
    rating: 4, difficulty: 3, hours: '4-6', grade: 'A', comment: 'ok',
  };
  const input: Pick<RateDraft, 'step' | 'answers' | 'opened' | 'deviceToken'> = {
    step: 'grade',
    answers: {
      professor: { slug: 'alex-rivera', name: 'Alex Rivera', department: 'CS' },
      comment: 'hi',
      updating,
      draft: { comment: '' },
    },
    opened: 'o.1.h.s',
    deviceToken: 'dev',
  };

  check('load returns null when nothing saved', loadRateDraft(now) === null);

  saveRateDraft(input, now);
  check('save writes to the known key', RATE_DRAFT_KEY in store);
  const loaded = loadRateDraft(now + 1000);
  check('round trip deep-equals the input', JSON.stringify(loaded && { step: loaded.step, answers: loaded.answers, opened: loaded.opened, deviceToken: loaded.deviceToken }) === JSON.stringify(input));
  check('round trip has v 1 and savedAt', loaded?.v === 1 && loaded.savedAt === now);

  check('draft at exactly the max age loads', loadRateDraft(now + DRAFT_MAX_AGE_MS) !== null);
  check('draft past the max age is dropped', loadRateDraft(now + DRAFT_MAX_AGE_MS + 1) === null);
  check('stale load removes the key', !(RATE_DRAFT_KEY in store));

  const valid = { v: 1, savedAt: now, ...input };
  const raw = (o: unknown) => { store[RATE_DRAFT_KEY] = typeof o === 'string' ? o : JSON.stringify(o); };

  raw({ ...valid, v: 2 });
  check('wrong version gives null', loadRateDraft(now) === null);

  raw('{nope');
  let threw = false;
  let r: RateDraft | null = null;
  try { r = loadRateDraft(now); } catch { threw = true; }
  check('unparseable gives null without throwing', !threw && r === null);

  raw({ ...valid, answers: { professor: input.answers.professor } });
  check('answers without comment gives null', loadRateDraft(now) === null);
  raw({ ...valid, answers: { comment: 'hi' } });
  check('answers without professor gives null', loadRateDraft(now) === null);
  raw({ ...valid, step: 'thanks' });
  check('step thanks gives null', loadRateDraft(now) === null);
  raw({ ...valid, step: 'nonsense' });
  check('unknown step gives null', loadRateDraft(now) === null);

  saveRateDraft(input, now);
  clearRateDraft();
  check('clear removes the key', !(RATE_DRAFT_KEY in store));

  const boom = () => { throw new Error('blocked'); };
  (globalThis as unknown as { sessionStorage: Storage }).sessionStorage = {
    getItem: boom, setItem: boom, removeItem: boom, clear: boom, key: boom,
    get length(): number { return boom(); },
  };
  threw = false;
  r = input as unknown as RateDraft;
  try { saveRateDraft(input, now); clearRateDraft(); r = loadRateDraft(now); } catch { threw = true; }
  check('throwing storage never throws and loads null', !threw && r === null);

  const start: RateStart = { opened: '20000.0.h.s', deviceToken: 'dev', counter: 3 };
  const d = (over: Partial<RateDraft>): RateDraft => ({ ...valid, v: 1, ...over }) as RateDraft;
  const kept = keepOpened(start, d({ deviceToken: 'dev', opened: '19000.0.h.s' }));
  check('keepOpened keeps the old opened for the same device', kept.opened === '19000.0.h.s' && kept.deviceToken === 'dev' && kept.counter === 3);
  check('keepOpened ignores another device', keepOpened(start, d({ deviceToken: 'other', opened: '19000.0.h.s' })) === start);
  check('keepOpened keeps an opened exactly 2 hours old', keepOpened(start, d({ opened: '12800.0.h.s' })).opened === '12800.0.h.s');
  check('keepOpened drops an opened over 2 hours old', keepOpened(start, d({ opened: '12799.0.h.s' })) === start);
  check('keepOpened drops an opened it cannot read', keepOpened(start, d({ opened: 'old' })) === start);
  check('keepOpened ignores a null draft', keepOpened(start, null) === start);
  check('keepOpened ignores a null opened', keepOpened(start, d({ opened: null })) === start);

  if (fails.length) {
    console.log(`\n${fails.length} FAILED`);
    return 1;
  }
  console.log('\nALL PASS');
  return 0;
}

if (argv[1] === fileURLToPath(import.meta.url)) process.exit(selftest());
