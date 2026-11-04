import type { Professor } from '../api';
import { score, percent } from './format';

// Ported from pickRanks in frontend/src/pages/Compare.tsx. Kept pure so the
// popup ranks the same way the site does — including ties, and difficulty
// where a lower number wins.

export type Direction = 'higher' | 'lower';

export type MetricRow = {
  label: string;
  values: (number | null)[];
  format: (value: number | null) => string;
  /** Indexes sharing the best value. Empty when every column ties, and empty
   *  for the rows that aren't a contest at all. */
  winners: number[];
  /** Draw stars beside the number. A flag rather than a check on the label,
   *  which renaming "Overall Rating" would have silently broken. */
  stars: boolean;
};

/** Below this a professor has too few ratings to call a winner on. Same
 *  threshold the site uses (MIN_RATINGS in Compare.tsx). */
export const MIN_RATINGS = 10;

/** Ties are judged on what each cell prints, not on a separately rounded copy
 *  of the number. Rounding on its own drifted from the display — Math.round
 *  takes 4.35 to 4.4 while toFixed prints "4.3" — so two cells reading "4.3"
 *  could still come out winner and loser. Order still comes from the raw
 *  values; rounding never reverses it. */
function rank(
  values: (number | null)[],
  low: boolean[],
  mode: Direction,
  format: (n: number) => string,
): number[] {
  const valid = values
    .map((v, i) => (v == null || low[i] ? null : { i, v, shown: format(v) }))
    .filter((e): e is { i: number; v: number; shown: string } => e !== null);

  // One printed value means everyone ties — no winner worth marking.
  if (new Set(valid.map((e) => e.shown)).size < 2) return [];

  const best = valid.reduce((a, b) => ((mode === 'higher' ? b.v > a.v : b.v < a.v) ? b : a));
  return valid.filter((e) => e.shown === best.shown).map((e) => e.i);
}

/** The count is already whole; the null branch only exists so every row
 *  formats the same way. score and percent come from format.ts so the popup's
 *  numbers can't drift between the Overview tiles and these rows. */
const whole = (n: number | null) => (n == null ? '—' : String(Math.round(n)));

type Spec = {
  label: string;
  pick: (p: Professor) => number | null;
  format: (n: number | null) => string;
  /** Left off where the row isn't a contest. */
  dir?: Direction;
  stars?: boolean;
};

/** The rows, plus which columns have too few ratings to rank. The screen
 *  greys those columns, and taking `low` from here saves it re-deriving the
 *  threshold check on its own. */
export function buildRows(profs: Professor[]): { rows: MetricRow[]; low: boolean[] } {
  const low = profs.map((p) => p.summary.numRatings < MIN_RATINGS);

  const spec: Spec[] = [
    { label: 'Overall Rating', pick: (p) => p.summary.rating, format: score, dir: 'higher', stars: true },
    { label: 'Difficulty', pick: (p) => p.summary.difficulty, format: score, dir: 'lower' },
    { label: 'Take Again', pick: (p) => p.summary.wouldTakeAgainPct, format: percent, dir: 'higher' },
    // Unranked, like the site's metricRows: more ratings isn't a better
    // professor, and painting 52 over 15 red reads as a fourth win.
    { label: '# of Ratings', pick: (p) => p.summary.numRatings, format: whole },
  ];

  const rows = spec.map(({ label, pick, format, dir, stars = false }) => {
    const values = profs.map(pick);
    return { label, values, format, stars, winners: dir ? rank(values, low, dir, format) : [] };
  });
  return { rows, low };
}
