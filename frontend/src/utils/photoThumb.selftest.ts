// Runnable self-check for photoThumb (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/photoThumb.selftest.ts
// Prints PASS/FAIL per check and exits non-zero on any failure.
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { photoThumb } from './photoThumb';

// Same vectors as backend/tests/test_photo_thumbs.py, so both sides name files alike.
const VECTORS: [string, string][] = [
  ['', 'bdcb81aee8d83'],
  ['a', '1c2ba782c97901'],
  ['https://cssh.northeastern.edu/wp-content/uploads/2020/01/Block-Aaron-414-x-512-px.png', '4fd4a9c944f20'],
  ['https://example.com/José-😀.jpg', '18a7399017e0d'],
];

function selftest(): number {
  const fails: string[] = [];
  const check = (label: string, cond: boolean) => {
    if (!cond) fails.push(label);
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  };

  for (const [url, hex] of VECTORS) {
    check(`thumb name for ${JSON.stringify(url)}`, photoThumb(url) === `/photos/${hex}.webp`);
  }

  console.log(fails.length ? `\n${fails.length} FAILED` : '\nall passed');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
