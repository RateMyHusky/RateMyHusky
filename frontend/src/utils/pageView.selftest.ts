// Runnable self-check for pageView (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/pageView.selftest.ts
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { cutView, setVisible, startTimer, viewToSend, visibleSeconds } from './pageView';
import type { PageView } from '../api/api';

const BASE: Omit<PageView, 'visibleSeconds'> = {
  itemType: 'professor', itemKey: 'alex-rivera', reachedSection: true, courseFilter: 'CS2500',
};

function selftest(): number {
  const fails: string[] = [];
  const check = (label: string, cond: boolean) => {
    if (!cond) fails.push(label);
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  };

  check('counts visible time only', visibleSeconds(setVisible(setVisible(startTimer(0, true), false, 3000), true, 10_000), 12_500) === 5);
  check('timer starts hidden', visibleSeconds(startTimer(0, false), 60_000) === 0);
  check('repeat visible is a no-op', visibleSeconds(setVisible(startTimer(0, true), true, 4000), 5000) === 5);
  check('short views dropped', viewToSend(BASE, 4) === null && viewToSend(BASE, 5)!.visibleSeconds === 5);
  // 6 s visible, hidden (sent), back at 7 s, hidden again at 15 s (sent), then pagehide (nothing left).
  check('time after a return is sent too', (() => {
    let t = setVisible(startTimer(0, true), false, 6000);
    const a = cutView(t, 6000, false, BASE); t = setVisible(a.timer, true, 7000);
    const b = cutView(setVisible(t, false, 15_000), 15_000, false, BASE);
    const c = cutView(b.timer, 15_001, false, BASE);
    return a.view?.visibleSeconds === 6 && b.view?.visibleSeconds === 8 && c.view === null; })());
  check('a dropped short view keeps counting', (() => {
    const a = cutView(setVisible(startTimer(0, true), false, 3000), 3000, false, BASE);
    const b = cutView(setVisible(setVisible(a.timer, true, 5000), false, 7000), 7000, false, BASE);
    return a.view === null && b.view?.visibleSeconds === 5; })());

  console.log(fails.length ? `${fails.length} FAIL(s): ` + fails.join(', ') : 'ALL PASS');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
