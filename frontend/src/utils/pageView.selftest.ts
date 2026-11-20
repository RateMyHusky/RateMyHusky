// Runnable self-check for pageView (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/pageView.selftest.ts
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { makeSender, setVisible, startTimer, viewToSend, visibleSeconds } from './pageView';
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
  check('short views dropped', viewToSend(BASE, 1) === null && viewToSend(BASE, 2)!.visibleSeconds === 2);
  check('sends once', (() => { const sent: PageView[] = []; const send = makeSender(v => sent.push(v));
    send(viewToSend(BASE, 5)); send(viewToSend(BASE, 9));   // hidden, then route change
    return sent.length === 1 && sent[0].visibleSeconds === 5; })());
  check('a dropped short view does not use up the send', (() => { const sent: PageView[] = []; const send = makeSender(v => sent.push(v));
    send(viewToSend(BASE, 1)); send(viewToSend(BASE, 4));
    return sent.length === 1 && sent[0].visibleSeconds === 4; })());

  console.log(fails.length ? `${fails.length} FAIL(s): ` + fails.join(', ') : 'ALL PASS');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
