import { lookup, MAX_CRNS, type Section, type Term } from './messages';
import { readRows, stillTeaching, type Row } from './table';
import { BADGE_TAG, badgeFor } from './badge';
import { USE_FIXTURES, fixtureLookup } from './fixtures';

/** Runs on Banner's registration pages and puts each section's rating in the
 *  results grid — under the instructor's name where the grid has an Instructor
 *  column, and with the name under the title where it doesn't.
 *
 *  Decorating an existing cell rather than adding a column is deliberate — the
 *  results table owns its own column model and rebuilds it on every render, so
 *  an injected <th> has to be fought for forever. Appending inside a cell
 *  leaves the column count alone. */

// Proof of life, and the first thing to check when nothing happens. A content
// script built as an ES module doesn't throw — it never executes at all, and
// no console anywhere says so. If this line is missing from the page console,
// the IIFE build pass is what's broken; don't debug anything else first.
console.log('[RateMyHusky] banner content script loaded');

/** Every answer so far, keyed "term:crn", for as long as the page is open. A
 *  sort, or paging back, redraws rows we've already asked about, and those
 *  come from here rather than another request. Null is settled with nothing
 *  to show. */
const answers = new Map<string, Section | null>();
/** Asked and not answered yet, so a redraw mid-request doesn't ask twice. */
const asking = new Set<string>();

const keyOf = (term: Term, crn: string) => `${term}:${crn}`;

/** Badges every drawn row it has an answer for, and asks about the rest in
 *  one request per term — never one per row. */
function decorate(): void {
  const unasked = new Map<Term, string[]>();

  for (const row of readRows()) {
    const key = keyOf(row.term, row.crn);
    if (answers.has(key)) {
      place(row, key, answers.get(key) ?? null);
    } else if (!asking.has(key)) {
      asking.add(key);
      unasked.set(row.term, [...(unasked.get(row.term) ?? []), row.crn]);
    }
  }

  for (const [term, crns] of unasked) {
    for (let i = 0; i < crns.length; i += MAX_CRNS) void ask(term, crns.slice(i, i + MAX_CRNS));
  }
}

async function ask(term: Term, crns: string[]): Promise<void> {
  const response = USE_FIXTURES ? await fixtureLookup(term, crns) : await lookup(term, crns);
  for (const crn of crns) {
    const key = keyOf(term, crn);
    asking.delete(key);
    // A failure settles as "nothing to show" instead of being retried. Every
    // redraw fires the observer, so retrying there would hammer a worker
    // that's already failing; a reload tries again.
    answers.set(key, response.ok ? (response.sections[crn] ?? null) : null);
  }
  decorate();
}

/** Leaves a row alone when its badge is already the right one, in the right
 *  cell. That's what keeps the observer from looping: inserting a badge is
 *  itself a mutation, and the pass it sets off finds nothing left to change.
 *  It's the row that gets cleared, not the cell, because crossing footable's
 *  phone breakpoint moves the badge between the Instructor and title cells. */
function place(row: Row, key: string, answer: Section | null): void {
  // Where the page shows who teaches the section now and our data names
  // someone else, the scrape is out of date and the rating isn't theirs, so
  // nothing is drawn. Skipped for fixtures, whose names are invented and
  // would never match.
  const section = USE_FIXTURES || stillTeaching(answer?.instructor ?? null, row.names) ? answer : null;

  const want = `${key}:${row.inInstructorCell ? 'instructor' : 'title'}`;
  const badges = row.tr.querySelectorAll(BADGE_TAG);
  if (badges.length === 1 && badges[0].getAttribute('data-key') === want && row.cell.contains(badges[0])) return;
  badges.forEach((b) => b.remove());

  const badge = badgeFor(section, want, {
    sample: USE_FIXTURES,
    inInstructorCell: row.inInstructorCell,
    coTaught: (row.names?.length ?? 0) > 1,
  });
  if (badge) row.cell.append(badge);
}

let queued = false;

/** Folds a burst of mutations — a redraw replaces every row — into one pass
 *  before the next paint. */
function schedule(): void {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => {
    queued = false;
    decorate();
  });
}

// The grid is rebuilt on every sort, page and filter, and the first results
// arrive long after document_idle, so when this runs there's often nothing to
// decorate yet. Watching the whole body catches all of it.
new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
schedule();

// Footable shows and hides columns on resize by changing their style, which
// the observer above never hears about — and it does so on a short delay of
// its own, so this waits for it before deciding which cell a badge goes in.
let resized = 0;
addEventListener('resize', () => {
  window.clearTimeout(resized);
  resized = window.setTimeout(schedule, 300);
});
