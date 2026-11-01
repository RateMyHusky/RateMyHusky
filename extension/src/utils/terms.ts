/* Banner terms arrive as display strings ("Fall 2026", "Summer 1 2026"), not
   anything sortable, so ordering them takes a little parsing. */

// Chronological within a year. "Summer 1"/"Summer 2" sit before the bare
// "Summer" so the longer label wins the startsWith check below.
const SEASONS = ['Spring', 'Summer 1', 'Summer 2', 'Summer', 'Fall'];

/** Sortable rank for a term string; -1 for anything unparseable, so terms we
 *  don't recognise sink rather than jumping to the top. */
export function termRank(term: string | null | undefined): number {
  if (!term) return -1;
  const year = Number(term.match(/\d{4}/)?.[0]);
  if (!year) return -1;
  const season = SEASONS.findIndex((s) => term.startsWith(s));
  return year * 10 + (season < 0 ? 0 : season);
}
