import type { Professor } from '../api';

// Ported from pickRanks in frontend/src/pages/Compare.tsx. Kept pure so the
// popup ranks the same way the site does — including ties, and difficulty
// where a lower number wins.

export type Direction = 'higher' | 'lower';

export type MetricRow = {
  label: string;
  values: (number | null)[];
  format: (value: number) => string;
  /** Indexes sharing the best value; empty when every column ties. */
  winners: number[];
};

/** Below this a professor has too few ratings to call a winner on. Same
 *  threshold the site uses (MIN_RATINGS in Compare.tsx). */
export const MIN_RATINGS = 10;

function rank(
  values: (number | null)[],
  eligible: boolean[],
  mode: Direction,
  decimals = 2,
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

const one = (n: number) => n.toFixed(1);
const pct = (n: number) => `${Math.round(n)}%`;
const whole = (n: number) => String(Math.round(n));

export function buildRows(profs: Professor[]): MetricRow[] {
  const eligible = profs.map((p) => p.summary.numRatings >= MIN_RATINGS);

  const spec: { label: string; pick: (p: Professor) => number | null; format: (n: number) => string; dir: Direction }[] = [
    { label: 'Overall Rating', pick: (p) => p.summary.rating, format: one, dir: 'higher' },
    { label: 'Difficulty', pick: (p) => p.summary.difficulty, format: one, dir: 'lower' },
    { label: 'Take Again', pick: (p) => p.summary.wouldTakeAgainPct, format: pct, dir: 'higher' },
    { label: '# of Ratings', pick: (p) => p.summary.numRatings, format: whole, dir: 'higher' },
  ];

  return spec.map(({ label, pick, format, dir }) => {
    const values = profs.map(pick);
    return { label, values, format, winners: rank(values, eligible, dir) };
  });
}
