// Runnable self-check for ratePrompt (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/ratePrompt.selftest.ts
// Prints PASS/FAIL per check and exits non-zero on any failure.
import { isDeepStrictEqual } from 'node:util';
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import {
  DAY_MS, MIN_DWELL_MS, REVISIT_DWELL_MS, STORAGE_KEY,
  analyticsPath, canShowPopup, dayKey, loadState, markDismissed, markShown, parseFrom, popupDelay,
  rateHref, recordRating, saveState, track, triggerFor, visitDay,
  type PromptState,
} from './ratePrompt';

function fakeStorage(initial?: string): Storage {
  const m = new Map<string, string>();
  if (initial !== undefined) m.set(STORAGE_KEY, initial);
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => { m.set(k, v); },
  } as unknown as Storage;
}

const throwingStorage = {
  getItem: () => { throw new Error('denied'); },
  setItem: () => { throw new Error('denied'); },
} as unknown as Storage;

function selftest(): number {
  const fails: string[] = [];
  const check = (label: string, cond: boolean) => {
    if (!cond) fails.push(label);
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  };
  const T = new Date(2026, 9, 31, 12, 0, 0).getTime();
  const fresh: PromptState = { dismissCount: 0, rated: [] };
  const sameAsFresh = (s: PromptState) => JSON.stringify(s) === JSON.stringify(fresh);

  check('analyticsPath strips to first segment',
    analyticsPath('/professors/alex-rivera') === '/professors' && analyticsPath('/rate') === '/rate'
    && analyticsPath('/') === '/' && analyticsPath('') === '/' && analyticsPath('/rate/') === '/rate');
  check('fresh state can show', canShowPopup(loadState(fakeStorage())!, 'a', T));

  let threw = false;
  try { saveState({ dismissCount: 1, rated: [] }, throwingStorage); } catch { threw = true; }
  check('throwing storage', loadState(throwingStorage) === null && !threw);
  check('null storage', loadState(null) === null);
  check('corrupt JSON', sameAsFresh(loadState(fakeStorage('{oops'))!));
  check('tampered dismissCount', loadState(fakeStorage('{"dismissCount":"x"}'))!.dismissCount === 0);

  const st = fakeStorage();
  const saved: PromptState = { lastShown: T, dismissCount: 2, lastDismiss: T, rated: ['x'], lastVisitDay: '2026-10-31' };
  saveState(saved, st);
  check('round trip', isDeepStrictEqual(loadState(st), saved));

  const shown = markShown(fresh, T);
  check('shown today blocks', !canShowPopup(shown, 'a', T + DAY_MS - 1) && canShowPopup(shown, 'a', T + DAY_MS));

  const dismissed = markDismissed(fresh, T);
  check('dismiss backs off a week',
    !canShowPopup(dismissed, 'a', T + 7 * DAY_MS - 1) && canShowPopup(dismissed, 'a', T + 7 * DAY_MS));

  const thrice = markDismissed(markDismissed(markDismissed(fresh, T), T + 8 * DAY_MS), T + 16 * DAY_MS);
  check('three dismissals is forever', !canShowPopup(thrice, 'a', T + 400 * DAY_MS));

  const rated = recordRating(fresh, 'b', T);
  check('recent rating blocks all',
    !canShowPopup(rated, 'a', T + 21 * DAY_MS - 1) && canShowPopup(rated, 'a', T + 21 * DAY_MS)
    && !canShowPopup(rated, 'b', T + 21 * DAY_MS));
  check('future timestamps from a clock set ahead expire',
    canShowPopup({ ...fresh, lastShown: T + 365 * DAY_MS, lastDismiss: T + 365 * DAY_MS, lastRated: T + 365 * DAY_MS }, 'a', T));

  const nullRated = recordRating(fresh, null, T);
  check('recordRating null slug', nullRated.lastRated === T && nullRated.rated.length === 0);
  check('recordRating no duplicates', recordRating(recordRating(fresh, 'b', T), 'b', T + 1).rated.length === 1);

  const first = visitDay(fresh, T);
  const same = visitDay(first.state, T + 1000);
  const later = visitDay(first.state, T + DAY_MS * 2);
  check('revisit', !first.revisit && !same.revisit && later.revisit
    && later.state.lastVisitDay === dayKey(T + DAY_MS * 2) && first.state.lastVisitDay === dayKey(T));

  check('delays', popupDelay(false) === 20000 && popupDelay(true) === 8000 && MIN_DWELL_MS < REVISIT_DWELL_MS);
  check('trigger', triggerFor('scroll', true) === 'revisit' && triggerFor('time', false) === 'time');
  check('parseFrom', parseFrom('tab_few') === 'tab_few' && parseFrom(null) === 'direct' && parseFrom('evil') === 'direct');
  check('rateHref', rateHref('alex-rivera', 'hero') === '/rate?professor=alex-rivera&from=hero'
    && rateHref('alex-rivera', 'hero', 'CS2500').endsWith('&course=CS2500'));

  let called = false;
  (globalThis as unknown as { window: unknown }).window = { gtag: () => { called = true; } };
  track('x', {});
  check('track off outside production', !called);

  console.log(fails.length ? `${fails.length} FAIL(s): ` + fails.join(', ') : 'ALL PASS');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
