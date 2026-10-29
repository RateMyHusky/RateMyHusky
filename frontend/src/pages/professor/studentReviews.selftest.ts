// Runnable self-check for studentReviews (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/pages/professor/studentReviews.selftest.ts
// Prints PASS/FAIL per check and exits non-zero on any failure.
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { defaultTab, filterByCourses, reportDescription } from './studentReviews';

function selftest(): number {
  const fails: string[] = [];
  const check = (label: string, cond: boolean) => {
    if (!cond) fails.push(label);
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  };

  check('students first when it has reviews', defaultTab({ students: 1, rmp: 9, reddit: 9 }) === 'students');
  check('skips empty tabs', defaultTab({ students: 0, rmp: 0, reddit: 2 }) === 'reddit');
  check('all empty falls back to rmp', defaultTab({ students: 0, rmp: 0, reddit: 0 }) === 'rmp');
  check('no selection keeps courseless reviews',
    filterByCourses([{ course: null }, { course: 'CS3500' }], new Set()).length === 2);
  check('selection filters',
    filterByCourses([{ course: 'CS2500' }, { course: 'CS3500' }], new Set(['CS3500'])).length === 1);
  check('report text carries the id and page', reportDescription('olin-guha', 'abc123').includes('abc123')
    && reportDescription('olin-guha', 'abc123').includes('/professors/olin-guha'));

  console.log(fails.length ? `${fails.length} FAIL(s): ` + fails.join(', ') : 'ALL PASS');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
