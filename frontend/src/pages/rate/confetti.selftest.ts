// Runnable self-check for the confetti physics (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/pages/rate/confetti.selftest.ts
// Prints PASS/FAIL per check and exits non-zero on any failure.
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { alive, confettiCount, launchScale, pieceScale, spawn, step } from './confetti';

function seeded(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function selftest(): number {
  const fails: string[] = [];
  const check = (label: string, cond: boolean) => {
    if (!cond) fails.push(label);
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  };

  check('confettiCount(1920) is 520', confettiCount(1920) === 520);
  check('confettiCount(1280) is 520', confettiCount(1280) === 520);
  check('confettiCount(390) is 390', confettiCount(390) === 390);
  check('launchScale(390) is .39', launchScale(390) === .39);
  check('launchScale(300) clamps to .38', launchScale(300) === .38);
  check('launchScale(3000) clamps to 1.4', launchScale(3000) === 1.4);

  const width = 1280, origin = { x: 100, y: 200 }, sp = launchScale(width), s = pieceScale(width);
  const pieces = spawn(5000, origin, -90, width, seeded(1));
  check('spawns the requested count', pieces.length === 5000);
  check('every piece starts at the origin', pieces.every((p) => p.x === origin.x && p.y === origin.y));
  const maxOff = 1.15 * 180 / Math.PI + 1e-9;
  check('launch angles lie within -90 +/- 65.9 degrees', pieces.every((p) => {
    const deg = Math.atan2(p.vy, p.vx) * 180 / Math.PI;
    return Math.abs(deg + 90) <= maxOff;
  }));
  check('speeds lie within [8*sp, 32*sp]', pieces.every((p) => {
    const v = Math.hypot(p.vx, p.vy);
    return v >= 8 * sp - 1e-9 && v <= 32 * sp + 1e-9;
  }));
  const share = (kind: string) => pieces.filter((p) => p.kind === kind).length / pieces.length * 100;
  check('ribbon share is about 12%', Math.abs(share('ribbon') - 12) <= 3);
  check('dot share is about 18%', Math.abs(share('dot') - 18) <= 3);

  const q = spawn(50, origin, -90, width, seeded(2));
  const before = q.map((p) => Math.abs(p.vx));
  q.forEach((p) => step(p, s));
  check('one step shrinks |vx|', q.every((p, i) => Math.abs(p.vx) < before[i]));
  q.forEach((p) => { for (let i = 0; i < 399; i++) step(p, s); });
  check('after 400 steps vy is at or below terminal speed',
    q.every((p) => p.vy <= (p.kind === 'dot' ? 3.2 : 2.2) * s + 1e-9));

  const p = q[0];
  check('alive is false below the viewport', (p.x = 10, p.y = 801, !alive(p, 1000, 770)));
  check('alive is false past the right edge', (p.x = 1061, p.y = 10, !alive(p, 1000, 770)));
  check('alive is true inside the viewport', (p.x = 500, p.y = 400, alive(p, 1000, 770)));

  if (fails.length) {
    console.log('\n' + fails.length + ' check(s) FAILED');
    return 1;
  }
  console.log('\nAll checks passed');
  return 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
