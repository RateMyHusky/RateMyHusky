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
};

/** Below this a professor has too few ratings to call a winner on. Same
 *  threshold the site uses (MIN_RATINGS in Compare.tsx). */
export const MIN_RATINGS = 10;

function rank(
  values: (number | null)[],
  eligible: boolean[],
  mode: Direction,
  decimals: number,
): number[] {
  const factor = 10 ** decimals;
  const valid = values
    .map((v, i) =>
      v == null || !eligible[i] ? null : { i, v: Math.round(v * factor) / factor },
    )
    .filter((e): e is { i: number; v: number } => e !== null);

  const distinct = [...new Set(valid.map((e) => e.v))].sort((a, b) =>
    mode === 'higher' ? b - a : a - b,
  );

  // One distinct value means everyone ties — no winner worth marking.
  return distinct.length >= 2 ? valid.filter((e) => e.v === distinct[0]).map((e) => e.i) : [];
}

/** The count is already whole; the null branch only exists so every row
 *  formats the same way. score and percent come from format.ts so the popup's
 *  numbers can't drift between the Overview tiles and these rows. */
const whole = (n: number | null) => (n == null ? '—' : String(Math.round(n)));

type Spec = {
  label: string;
  pick: (p: Professor) => number | null;
  format: (n: number | null) => string;
  /** How many decimals the cell actually prints. Ties are judged at that
   *  precision, so two columns reading "4.0" can't be ranked apart — 4.04
   *  beating 4.00 in brand red, with both showing the same number, looks
   *  like the popup is making it up. */
  decimals: number;
  /** Left off where the row isn't a contest. */
  dir?: Direction;
};

export function buildRows(profs: Professor[]): MetricRow[] {
  const eligible = profs.map((p) => p.summary.numRatings >= MIN_RATINGS);

  const spec: Spec[] = [
    { label: 'Overall Rating', pick: (p) => p.summary.rating, format: score, decimals: 1, dir: 'higher' },
    { label: 'Difficulty', pick: (p) => p.summary.difficulty, format: score, decimals: 1, dir: 'lower' },
    { label: 'Take Again', pick: (p) => p.summary.wouldTakeAgainPct, format: percent, decimals: 0, dir: 'higher' },
    // Unranked, like the site's metricRows: more ratings isn't a better
    // professor, and painting 52 over 15 red reads as a fourth win.
    { label: '# of Ratings', pick: (p) => p.summary.numRatings, format: whole, decimals: 0 },
  ];

  return spec.map(({ label, pick, format, decimals, dir }) => {
    const values = profs.map(pick);
    return {
      label,
      values,
      format,
      winners: dir ? rank(values, eligible, dir, decimals) : [],
    };
  });
}
