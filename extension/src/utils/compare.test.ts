import { describe, expect, it } from 'vitest';
import type { Professor } from '../api';
import { buildRows, MIN_RATINGS } from './compare';

function prof(summary: Partial<Professor['summary']>): Professor {
  return {
    summary: {
      rating: null,
      difficulty: null,
      wouldTakeAgainPct: null,
      numRatings: MIN_RATINGS,
      numComments: 0,
      hoursPerWeek: null,
      ...summary,
    },
  } as Professor;
}

const row = (label: string, profs: Professor[]) =>
  buildRows(profs).rows.find((r) => r.label === label)!;

describe('buildRows', () => {
  it('marks the higher rating and the lower difficulty as winners', () => {
    const profs = [prof({ rating: 4.6, difficulty: 3.1 }), prof({ rating: 3.4, difficulty: 2.7 })];
    expect(row('Overall Rating', profs).winners).toEqual([0]);
    expect(row('Difficulty', profs).winners).toEqual([1]);
  });

  it('judges ties on the printed value, so two cells reading 4.3 both win', () => {
    // toFixed prints both as "4.3" even though 4.34 > 4.26.
    const profs = [prof({ rating: 4.34 }), prof({ rating: 4.26 }), prof({ rating: 3.0 })];
    expect(row('Overall Rating', profs).winners).toEqual([0, 1]);
  });

  it('calls no winner when every column prints the same', () => {
    expect(row('Overall Rating', [prof({ rating: 4 }), prof({ rating: 4 })]).winners).toEqual([]);
  });

  it('leaves out professors with too few ratings, and flags them', () => {
    const profs = [prof({ rating: 5, numRatings: MIN_RATINGS - 1 }), prof({ rating: 4 }), prof({ rating: 3 })];
    expect(row('Overall Rating', profs).winners).toEqual([1]);
    expect(buildRows(profs).low).toEqual([true, false, false]);
  });

  it('never ranks the rating count', () => {
    expect(row('# of Ratings', [prof({ numRatings: 52 }), prof({ numRatings: 15 })]).winners).toEqual([]);
  });

  it('skips missing values instead of treating them as zero', () => {
    const profs = [prof({ wouldTakeAgainPct: null }), prof({ wouldTakeAgainPct: 60 }), prof({ wouldTakeAgainPct: 90 })];
    expect(row('Take Again', profs).winners).toEqual([2]);
  });
});
