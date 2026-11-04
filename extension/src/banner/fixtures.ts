import type { LookupResponse, Section, Term } from './messages';

/** Flip once step 4 lands and the worker answers from /api/banner/sections.
 *  Until then the content script never messages the worker at all. */
export const USE_FIXTURES = true;

/** Stands in for the endpoint, answering for any CRN so badges appear on
 *  whatever you search, not only on one page somebody captured. The CRN picks
 *  the case, which spreads all four across every page of results.
 *
 *  The names are invented on purpose, and every badge built from this says
 *  SAMPLE. On the signed-in pages the badge sits under the real instructor's
 *  name in Banner's own column, and an invented rating there would otherwise
 *  read, in any screenshot, as that professor's real score. */
export async function fixtureLookup(_term: Term, crns: string[]): Promise<LookupResponse> {
  const sections: Record<string, Section> = {};
  for (const crn of crns) {
    const n = Number(crn);
    switch (n % 4) {
      case 0: // matched, with ratings
        sections[crn] = {
          instructor: 'Sample, Rated',
          slug: 'sample-rated',
          rating: 3 + (n % 20) / 10,
          numRatings: (n % 60) + 1,
        };
        break;
      case 1: // matched, but nobody has rated them yet
        sections[crn] = { instructor: 'Sample, Unrated', slug: 'sample-unrated', rating: null, numRatings: 0 };
        break;
      case 2: // the matcher abstained: a name, and nothing claimed about it
        sections[crn] = { instructor: 'Sample, Unmatched', slug: null, rating: null, numRatings: 0 };
        break;
      // 3: left out entirely — a CRN our data has never seen.
    }
  }
  return { ok: true, sections };
}
