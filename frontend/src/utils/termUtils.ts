/**
 * Returns a numeric sort key for a term title where higher = more recent.
 * Primary sort is by year; secondary is by season/modifier within the year.
 *
 * Order within a year (highest → most recent):
 *   Fall (7) > Fall A (6) > Summer 2 (5) > Summer / Full Summer (4) > Summer 1 (3) > Spring (2) > Spring A (1)
 */
export function termSortKey(title: string): number {
  if (!title) return 0;
  const lower = title.toLowerCase();
  // Try word-bounded year first (e.g. "Fall 2025"), then 4-digit prefix of 6-digit code (e.g. "202510")
  const yearMatch = lower.match(/\b(20\d{2})\b/) ?? lower.match(/(20\d{2})\d{2}/);
  if (!yearMatch) return 0;
  const year = parseInt(yearMatch[1]);

  let subKey = 0;
  if (/\bfall\b/.test(lower)) {
    // "Fall A 2025" has "fall a" directly; "Fall 2024 Law A Term" does NOT
    subKey = /\bfall\s+a\b/.test(lower) ? 6 : 7;
  } else if (/\bsummer\b/.test(lower)) {
    // Summer 1 ends first, the full session next, Summer 2 last.
    if (/\bsummer\s+2\b/.test(lower)) subKey = 5;
    else if (/\bsummer\s+1\b/.test(lower)) subKey = 3;
    else subKey = 4; // Summer, Full Summer, Summer Full
  } else if (/\bspring\b/.test(lower)) {
    subKey = /\bspring\s+a\b/.test(lower) ? 1 : 2;
  }
  // Winter and unknown terms get subKey = 0

  return year * 10 + subKey;
}

const SEASONS = ['spring', 'summer', 'fall'] as const;

/** "Summer 1 2026" / "Summer Full 2026" -> "Summer 2026", short enough for a stat card. */
export const seasonYear = (label: string) => label.replace(/^Summer (?:1|2|Full) /, 'Summer ');

/**
 * Reads a Banner term label ("Fall 2026", "Summer 1 2026", "Winter 2027") against today:
 * "This semester", "Next semester", "Upcoming", "Last semester", "Last summer", "2 years ago".
 * Summer sessions count as one summer, Winter as spring. Null for a label it can't read.
 */
export function relativeTerm(label: string, now = new Date()): string | null {
  const m = label.match(/^(Fall|Winter|Spring|Summer(?: 1| 2| Full)?) (\d{4})$/);
  if (!m) return null;
  const season = m[1].startsWith('Summer') ? 'summer' : m[1] === 'Fall' ? 'fall' : 'spring';
  const index = (year: number, s: typeof SEASONS[number]) => year * 3 + SEASONS.indexOf(s);
  const month = now.getMonth();
  const current = index(now.getFullYear(), month < 4 ? 'spring' : month < 8 ? 'summer' : 'fall');
  const term = index(Number(m[2]), season);
  const isSummer = season === 'summer';

  if (term > current) {
    // The first spring/fall after now, skipping a summer the same way lastSemester does.
    let nextSemester = current + 1;
    if (nextSemester % 3 === SEASONS.indexOf('summer')) nextSemester += 1;
    if (term === nextSemester) return 'Next semester';
    if (isSummer && term - current < 3) return 'Next summer';
    return 'Upcoming';
  }
  if (term === current) return isSummer ? 'This summer' : 'This semester';
  // The newest spring/fall before now; summers in between don't count as a semester.
  let lastSemester = current - 1;
  if (lastSemester % 3 === SEASONS.indexOf('summer')) lastSemester -= 1;
  if (term === lastSemester) return 'Last semester';
  if (isSummer && current - term < 3) return 'Last summer';
  const years = Math.max(1, Math.floor((current - term) / 3));
  return years === 1 ? '1 year ago' : `${years} years ago`;
}
