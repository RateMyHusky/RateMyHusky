import type { Term } from './messages';

/** One section in Banner's results grid, and where its badge goes. */
export type Row = {
  term: Term;
  crn: string;
  tr: HTMLElement;
  /** The Instructor cell when the grid shows one, else the title cell. */
  cell: HTMLElement;
  inInstructorCell: boolean;
  /** Who Banner says teaches the section right now, or null where the grid
   *  has no Instructor column to read it from. */
  names: string[] | null;
};

/** Every section the grid has drawn, read off the title link.
 *
 *  The link is `<a class="section-details-link" data-attributes="202730,30351">`
 *  — term code and CRN together — which survives everything else the grid does
 *  to its columns. Footable hides the CRN column at narrow widths, the Term
 *  column only ever holds the description ("Spring 2027 Semester") and never
 *  the code the endpoint needs, and students can reorder columns.
 *
 *  Anchored on the title cell, not on the link class alone: jQuery UI keeps
 *  copies of these links in hover tooltips hung off <body>, and those are no
 *  place for a badge. Footable's detail rows hold no title cell either.
 *
 *  Whether there's an Instructor column depends on the page. Browse Classes,
 *  and the catalog's View Sections, have none. The signed-in pages — Plan
 *  Ahead, and presumably Register for Classes — do, and that's where the
 *  badge belongs: beside the name. */
export function readRows(root: ParentNode = document): Row[] {
  const rows: Row[] = [];
  const links = root.querySelectorAll<HTMLAnchorElement>(
    'td[data-property="courseTitle"] a.section-details-link[data-attributes]',
  );
  for (const link of links) {
    const [term, crn] = (link.dataset.attributes ?? '').split(',');
    // Anything else means Banner changed the markup; skip it rather than ask
    // the endpoint about a CRN that isn't one.
    if (!/^\d{6}$/.test(term ?? '') || !/^\d+$/.test(crn ?? '')) continue;
    const title = link.closest('td');
    const tr = link.closest('tr');
    if (!title || !tr || !isSearchResult(tr)) continue;

    const instructor = tr.querySelector<HTMLElement>('td[data-property="instructor"]');
    // Footable hides the column at its phone breakpoint, and a badge in a
    // hidden cell is a badge nobody sees. The names are still in the DOM, so
    // they're read either way.
    const shown = instructor && getComputedStyle(instructor).display !== 'none';
    rows.push({
      term,
      crn,
      tr,
      cell: shown ? instructor : title,
      inInstructorCell: !!shown,
      names: instructor ? readNames(instructor) : null,
    });
  }
  return rows;
}

/** Columns only the class-search results grid has. Banner draws the student's
 *  own registered and planned sections — Register for Classes' Summary, Plan
 *  Ahead's plan — with the same title-cell markup, but those grids fold
 *  subject, number and section into one Details column. Their CRNs are the
 *  student's schedule, and the extension never reads that (Privacy §9), so a
 *  row is only ours when it has one of these. Several, not one, so a student
 *  hiding a column doesn't switch the badges off. */
const SEARCH_ONLY = ['subjectDescription', 'courseNumber', 'sequenceNumber']
  .map((p) => `td[data-property="${p}"]`)
  .join(', ');

export function isSearchResult(tr: Pick<Element, 'querySelector'>): boolean {
  return tr.querySelector(SEARCH_ONLY) !== null;
}

/** The names Banner lists in an Instructor cell, from its mailto links.
 *  Null when it has none to read — an instructor with no published address
 *  prints as plain text, and an empty list would tell stillTeaching "nobody
 *  teaches this", hiding a badge our data and Banner agree on. Null is
 *  "unknown", and stillTeaching only says no when it knows. */
export function readNames(cell: Pick<Element, 'querySelectorAll'>): string[] | null {
  const names = [...cell.querySelectorAll('a.email')]
    .map((a) => a.textContent?.trim() ?? '')
    .filter(Boolean);
  return names.length > 0 ? names : null;
}

const fold = (name: string) => name.toLowerCase().replace(/\s+/g, ' ').trim();

/** Whether our data's instructor for a CRN is still among the people Banner
 *  lists for it. Our data is a weekly scrape and Banner's page is live, so when
 *  they disagree the section was reassigned since — and our rating belongs to
 *  someone who no longer teaches it.
 *
 *  This only ever says no; it never decides a match. Which professor a name is
 *  stays the matcher's call, made in scraper/match_banner_instructors.py. */
export function stillTeaching(instructor: string | null, names: string[] | null): boolean {
  if (names === null || instructor === null) return true;
  const ours = fold(instructor);
  return names.some((n) => fold(n) === ours);
}
