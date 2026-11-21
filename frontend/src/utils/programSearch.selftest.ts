// Runnable self-check for programSearch (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/programSearch.selftest.ts
import { searchPrograms } from './programSearch';

const L = [
  { name: 'Computer Science, BSCS', college: 'Khoury' },
  { name: 'Computer Science and Design, BS', college: 'Khoury' },
  { name: 'Computer Engineering, BSCompE', college: 'Engineering' },
  { name: 'Data Science, BS', college: 'Khoury' },
];
const names = (g: ReturnType<typeof searchPrograms>) => g.flatMap((x) => x.programs.map((p) => p.name));

const fails: string[] = [];
const check = (label: string, cond: boolean) => {
  if (!cond) fails.push(label);
  console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
};

check('blank query', searchPrograms(L, '  ', []).length === 0);
check('prefix tokens', names(searchPrograms(L, 'comp sci', [])).join('|') === 'Computer Science, BSCS|Computer Science and Design, BS');
check('grouped by college, sorted', searchPrograms(L, 'comp', []).map((g) => g.college).join('|') === 'Engineering|Khoury');
check('excluded left out', !names(searchPrograms(L, 'comp', ['Computer Science, BSCS'])).includes('Computer Science, BSCS'));
check('case-insensitive', names(searchPrograms(L, 'DATA', [])).length === 1);
check('limit', names(searchPrograms(L, 'c', [], 2)).length === 2);
check('no mid-word match', searchPrograms(L, 'puter', []).length === 0);

const M = [
  { name: 'Computer Science and Business, BS', college: 'Business' },
  { name: 'Computer Science and Design, BS', college: 'Arts' },
  { name: 'Computer Science and Math, BS', college: 'Science' },
  { name: 'Computer Science, BSCS', college: 'Khoury' },
];
check('common major survives the limit', names(searchPrograms(M, 'computer science', [], 2)).includes('Computer Science, BSCS'));
check('comma query matches', names(searchPrograms(M, 'computer science, bs', [])).includes('Computer Science, BSCS'));

if (fails.length) { console.log(`\n${fails.length} FAILED`); process.exit(1); }
console.log('\nALL PASS');
