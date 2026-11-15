import type { Review, StudentReview } from '../api';

export type Source = 'rmh' | 'rmp';
export type Sort = 'newest' | 'highest' | 'lowest';

/** Both kinds of review in one shape, so the list renders and sorts them
 *  together. */
export type ReviewItem = {
  key: string;
  source: Source;
  rating: number;
  course: string | null;
  /** What the card prints: a term for RateMyHusky, a month for RMP. */
  when: string | null;
  /** Milliseconds, for sorting newest first. 0 when unknown. */
  time: number;
  comment: string;
  difficulty: number | null;
  tags: string[];
};

// Roughly where each term starts, as a month (0 = January). Only the order
// matters: these sort a "Fall 2025" review against RMP reviews that carry real
// dates. Every season ratings._TERM_SEASONS can produce is here — survey_
// reviews.when() passes the term label through verbatim.
const SEASON_MONTH: Record<string, number> = {
  winter: 0,
  spring: 1,
  summer: 4, // "Summer 2025" and "Summer Full 2025"
  'summer 1': 4,
  'summer 2': 6,
  'summer full': 4,
  fall: 8,
};

/** "Fall 2025" -> 1 Sept 2025, "Summer 2 2025" -> 1 July 2025. A bare year,
 *  which small classes get in place of the term so a review can't be traced
 *  to a section, -> 1 July of it: mid-year, between its terms. Anything else
 *  -> 0, which sorts last. */
export function termTime(label: string | null): number {
  const text = (label ?? '').trim();
  const term = /^(winter|spring|fall|summer(?:\s+(?:1|2|full))?)\s+(\d{4})$/i.exec(text);
  if (term) {
    const season = term[1].toLowerCase().replace(/\s+/g, ' ');
    return Date.UTC(Number(term[2]), SEASON_MONTH[season], 1);
  }
  const year = /^(\d{4})$/.exec(text);
  return year ? Date.UTC(Number(year[1]), 6, 1) : 0;
}

function monthYear(value: string): string {
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
}

/** Older RMP reviews have no id and two can be word for word the same, so
 *  the key falls back to the content plus how many times it's been seen. */
function keyer(): (base: string) => string {
  const seen = new Map<string, number>();
  return (base) => {
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return `${base}-${n}`;
  };
}

export function mergeReviews(rmp: Review[], student: StudentReview[]): ReviewItem[] {
  const key = keyer();
  return [
    ...student.map((r) => ({
      key: key(`rmh:${r.id}`),
      source: 'rmh' as const,
      rating: r.rating,
      course: r.course,
      when: r.when,
      time: termTime(r.when),
      comment: r.comment,
      difficulty: null,
      tags: [],
    })),
    ...rmp.map((r) => ({
      key: key(
        r.id != null
          ? `rmp:${r.id}`
          : `rmp:${JSON.stringify([r.date, r.courseCode, r.quality, r.comment])}`,
      ),
      source: 'rmp' as const,
      rating: r.quality,
      course: r.courseCode,
      when: r.date ? monthYear(r.date) : null,
      time: Date.parse(r.date) || 0,
      comment: r.comment,
      difficulty: r.difficulty,
      tags: r.tags
        .split('--')
        .map((t) => t.trim().toLowerCase())
        .filter(Boolean),
    })),
  ];
}

/** Ties on rating fall back to newest first. */
export function sortReviews(items: ReviewItem[], sort: Sort): ReviewItem[] {
  const out = [...items];
  if (sort === 'highest') return out.sort((a, b) => b.rating - a.rating || b.time - a.time);
  if (sort === 'lowest') return out.sort((a, b) => a.rating - b.rating || b.time - a.time);
  return out.sort((a, b) => b.time - a.time);
}
