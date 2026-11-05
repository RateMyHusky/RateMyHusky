// Runnable self-check for compareScore (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/utils/compareScore.selftest.ts
// Prints PASS/FAIL per check and exits non-zero on any failure.
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import { scoreProfessors, winnerSentence, droppedSentence } from './compareScore';
import type { ScoreMetric } from './compareScore';

const ratingMetric = (values: (number | null)[]): ScoreMetric => ({
  id: 'rating', weight: 3, better: 'higher', scale: (v) => v / 5, values,
});
const difficultyMetric = (values: (number | null)[]): ScoreMetric => ({
  id: 'difficulty', weight: 1.5, better: 'lower', scale: (v) => (5 - v) / 4, values,
});
const takeAgainMetric = (values: (number | null)[]): ScoreMetric => ({
  id: 'takeAgain', weight: 2, better: 'higher', scale: (v) => v / 100, values,
});

function selftest(): number {
  const fails: string[] = [];
  const check = (label: string, cond: boolean) => {
    if (!cond) fails.push(label);
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  };
  const near = (a: number, b: number) => Math.abs(a - b) <= 0.05;

  // Slots: 0 Lerner, 1 Nunez, 2 Fontenot, 3 Mislove
  const m = [
    ratingMetric([3.61, 3.54, 2.82, 4.9]),
    difficultyMetric([4.3, 3.9, 3.3, 3.8]),
    takeAgainMetric([61, 67, 48, 100]),
  ];
  const last = (s: number) => ['Lerner', 'Nunez', 'Fontenot', 'Mislove'][s];

  const three = scoreProfessors([0, 1, 2], m);
  check('three-way scores are 56.1 / 59.6 / 50.6',
    !!three && near(three.scores[0], 56.1) && near(three.scores[1], 59.6) && near(three.scores[2], 50.6));
  check('three-way winner is Nunez, runner-up Lerner',
    three?.kind === 'winner' && three.winner === 1 && three.runnerUp === 0);

  const two = scoreProfessors([0, 1], m);
  check('a third professor does not reorder the other two', two?.kind === 'winner' && two.winner === 1);
  check('two-way sentence names margin and trade-off',
    two?.kind === 'winner' && winnerSentence(two, last) ===
      "Nunez scores 60 to Lerner's 56. Ahead on difficulty and would-take-again rate, which outweighs Lerner's higher overall rating.");

  const four = scoreProfessors([0, 1, 2, 3], m);
  check('four-way winner is Mislove, runner-up Nunez', four?.kind === 'winner' && four.winner === 3 && four.runnerUp === 1);
  check('four-way sentence is exact',
    four?.kind === 'winner' && winnerSentence(four, last) ===
      "Mislove scores 83 to Nunez's 60. Ahead on overall rating, difficulty, and would-take-again rate.");

  const tinyLead = scoreProfessors([0, 1], [
    ratingMetric([3.61, 3.54]), difficultyMetric([3.5, 3.5]), takeAgainMetric([60, 60]),
  ]);
  check('a 0.07 rating-only lead is a tie',
    tinyLead?.kind === 'tie' && tinyLead.tied.length === 2 && tinyLead.tied.includes(0) && tinyLead.tied.includes(1));

  const inBand = scoreProfessors([0, 1], [ratingMetric([4.0, 3.905])]);
  check('1.9 points apart is a tie', inBand?.kind === 'tie');
  const outBand = scoreProfessors([0, 1], [ratingMetric([4.0, 3.895])]);
  check('2.1 points apart is a winner', outBand?.kind === 'winner');

  const band = scoreProfessors([0, 1, 2, 3], [ratingMetric([3.5, 3.45, 3.425, 3.0])]);
  check('tie holds every contender within 2 points of the top, in score order',
    band?.kind === 'tie' && band.tied.join() === '0,1,2');

  const missing = scoreProfessors([0, 1, 2], [
    ratingMetric([3.61, 3.54, 2.82]), difficultyMetric([4.3, 3.9, 3.3]), takeAgainMetric([61, 67, null]),
  ]);
  check('missing would-take-again is dropped and reported',
    !!missing && JSON.stringify(missing.dropped) === JSON.stringify([{ id: 'takeAgain', missing: [2] }]));
  check('scores use only the counted metrics',
    !!missing && near(missing.scores[0], (100 * (3 * 0.722 + 1.5 * 0.175)) / 4.5));

  check('droppedSentence, one name',
    droppedSentence({ id: 'takeAgain', missing: [2] }, () => 'Mark Fontenot') ===
      "Would take again isn't counted: Mark Fontenot has no data for it.");
  check('droppedSentence, two names',
    droppedSentence({ id: 'takeAgain', missing: [2, 1] }, (s) => (s === 2 ? 'Mark Fontenot' : 'Lucia Nunez')) ===
      "Would take again isn't counted: Mark Fontenot and Lucia Nunez have no data for it.");

  const outside = scoreProfessors([0, 1], [
    ratingMetric([3.61, 3.54, null]), difficultyMetric([4.3, 3.9, 3.3]), takeAgainMetric([61, 67, 48]),
  ]);
  check('a missing value outside the contenders drops nothing', !!outside && outside.dropped.length === 0);

  check('one contender returns null', scoreProfessors([0], m) === null);
  check('every metric dropped returns null',
    scoreProfessors([0, 1], [ratingMetric([null, 3.5]), takeAgainMetric([60, null])]) === null);

  console.log(fails.length ? `${fails.length} FAIL(s): ` + fails.join(', ') : 'ALL PASS');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
