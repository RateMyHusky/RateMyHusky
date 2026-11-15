/// <reference types="vite/client" />
import { extensionAlive, lookup, MAX_CRNS, openProfessor, type Section, type Term } from './messages';
import { readRows, stillTeaching, type Row } from './table';
import { BADGE_TAG, badgeFor, pendingBadge } from './badge';
import { maybeShowHint } from './hint';
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
// Dev builds only (`npm run dev:content`), so Banner's console stays clean.
if (import.meta.env.DEV) console.log('[RateMyHusky] banner content script loaded');

// Turning the setting on injects this into Banner tabs that are already open
// (background.ts), and a later page load gets the registered copy. Both run in
// this extension's one isolated world, so the second sees the first's flag and
// stands down rather than doubling every request.
const LOADED = '__rmhBannerLoaded';
const world = globalThis as typeof globalThis & { [LOADED]?: true };

/** Every answer so far, keyed "term:crn", for as long as the page is open. A
 *  sort, or paging back, redraws rows we've already asked about, and those
 *  come from here rather than another request. Null is settled with nothing
 *  to show. */
const answers = new Map<string, Section | null>();
/** Asked and not answered yet, so a redraw mid-request doesn't ask twice. */
const asking = new Set<string>();

/** A lookup that failed in a way worth retrying (429, 5xx, timeout): how many
 *  times so far, and not before when. Not cached as "nothing to show", since
 *  Banner's registration UI is one long-lived page, and a single 429 on a
 *  campus network would otherwise blank its badges until a reload. */
const failed = new Map<string, { tries: number; until: number }>();
const MAX_TRIES = 5;
/** 2s, 4s, 8s, 16s, then give up for this page. */
const backoff = (tries: number) => 1000 * 2 ** tries;

/** Set once this script should do nothing more: Banner access was switched
 *  off, or the extension updated under the page. */
let stopped = false;

const keyOf = (term: Term, crn: string) => `${term}:${crn}`;

// A title link is the student's explicit choice of a section to inspect.
// Use it to associate Banner's already-rendered detail dialog with that row.
let activeDetailKey: string | null = null;
function rememberDetail(event: MouseEvent): void {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const link = target.closest('a.section-details-link[data-attributes]');
  if (!link) return;
  const row = readRows().find((r) => r.tr.contains(link));
  if (row) activeDetailKey = keyOf(row.term, row.crn);
}

/** If Banner opens a section-detail dialog, add a badge using the selected row.
 *  Do not query Banner or infer identity from modal text. If a different dialog
 *  is open or the instructor has changed, abstain. */
function decorateDetail(): void {
  if (!activeDetailKey || stopped) return;
  const row = readRows().find((r) => keyOf(r.term, r.crn) === activeDetailKey);
  const answer = answers.get(activeDetailKey);
  if (!row || !answer || !answer.instructor ||
      !stillTeaching(answer.instructor, row.names)) return;
  const dialogs = document.querySelectorAll<HTMLElement>(
    '[role="dialog"], .ui-dialog, .modal.show',
  );
  for (const dialog of dialogs) {
    if (getComputedStyle(dialog).display === 'none' ||
        dialog.getAttribute('aria-hidden') === 'true' || !dialog.getClientRects().length) continue;
    // A dialog may be unrelated (e.g. a login prompt). Require section context.
    const content = dialog.querySelector<HTMLElement>('.ui-dialog-content, .modal-body') ?? dialog;
    const text = content.textContent ?? '';
    const title = row.tr.querySelector<HTMLElement>('td[data-property="courseTitle"] a.section-details-link')
      ?.textContent?.trim() ?? '';
    if (!text.includes(row.crn) &&
        !(title.length > 6 && text.includes(title) && text.includes(answer.instructor))) continue;
    const badgeKey = `detail:${activeDetailKey}`;
    const existing = content.querySelector(BADGE_TAG);
    if (existing?.getAttribute('data-key') === badgeKey) continue;
    content.querySelectorAll(BADGE_TAG).forEach((badge) => badge.remove());
    const badge = badgeFor(answer, badgeKey, {
      sample: USE_FIXTURES, inInstructorCell: false, coTaught: false,
      onOpen: answer.slug ? () => openProfessor(answer.slug!) : undefined,
    });
    if (badge) content.append(badge);
  }
}


/** Badges every drawn row it has an answer for, and asks about the rest in
 *  one request per term — never one per row. */
function decorate(): void {
  if (stopped) return;
  if (!extensionAlive()) return stop(false);

  const unasked = new Map<Term, string[]>();
  const now = Date.now();

  for (const row of readRows()) {
    const key = keyOf(row.term, row.crn);
    if (answers.has(key)) {
      place(row, key, answers.get(key) ?? null);
      continue;
    }
    // Waiting out a backoff: the row keeps its shimmer, and the timer set
    // when it failed brings this pass round again.
    const wait = failed.get(key);
    if (!asking.has(key) && !(wait && now < wait.until)) {
      asking.add(key);
      unasked.set(row.term, [...(unasked.get(row.term) ?? []), row.crn]);
    }
    showPending(row, key);
  }

  for (const [term, crns] of unasked) {
    for (let i = 0; i < crns.length; i += MAX_CRNS) void ask(term, crns.slice(i, i + MAX_CRNS));
  }
}

async function ask(term: Term, crns: string[]): Promise<void> {
  const response = USE_FIXTURES ? await fixtureLookup(term, crns) : await lookup(term, crns);
  if (!response.ok && response.disabled) return stop(true);

  let soonest = Infinity;
  for (const crn of crns) {
    const key = keyOf(term, crn);
    asking.delete(key);
    if (response.ok) {
      failed.delete(key);
      answers.set(key, response.sections[crn] ?? null);
      continue;
    }
    // Retried on a timer, never from the observer: every redraw fires it,
    // and retrying there would hammer a server that's already refusing.
    const tries = (failed.get(key)?.tries ?? 0) + 1;
    if (!response.retry || tries > MAX_TRIES) {
      failed.delete(key);
      answers.set(key, null);
    } else {
      const delay = backoff(tries);
      failed.set(key, { tries, until: Date.now() + delay });
      soonest = Math.min(soonest, delay);
    }
  }
  if (soonest !== Infinity) window.setTimeout(schedule, soonest);
  decorate();
  decorateDetail();
}

/** Stops watching the page. With `clear`, also takes every badge down: the
 *  student switched Banner access off, and what they see should say so. After
 *  an extension update the badges stay — they're still right, and the new
 *  version takes over on the next page load. */
function stop(clear: boolean): void {
  stopped = true;
  // Lets the next copy in: switching the setting back on injects one, and it
  // would otherwise stand down for this stopped one.
  delete world[LOADED];
  observer.disconnect();
  document.removeEventListener('click', rememberDetail, true);
  removeEventListener('resize', onResize);
  if (clear) document.querySelectorAll(BADGE_TAG).forEach((b) => b.remove());
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
    onOpen: section?.slug ? () => openProfessor(section.slug!) : undefined,
  });
  if (badge) {
    row.cell.append(badge);
    if (section?.slug) void maybeShowHint();
  }
}

/** A shimmer where the badge will go. Keyed like place's badges, so the
 *  observer pass it sets off finds it already there and leaves it. */
function showPending(row: Row, key: string): void {
  const want = `${key}:pending`;
  const badges = row.tr.querySelectorAll(BADGE_TAG);
  if (badges.length === 1 && badges[0].getAttribute('data-key') === want && row.cell.contains(badges[0])) return;
  badges.forEach((b) => b.remove());
  row.cell.append(pendingBadge(want));
}

let queued = false;

/** Folds a burst of mutations — a redraw replaces every row — into one pass
 *  before the next paint. */
function schedule(): void {
  if (queued || stopped) return;
  queued = true;
  requestAnimationFrame(() => {
    queued = false;
    decorate();
    decorateDetail();
  });
}

// The grid is rebuilt on every sort, page and filter, and the first results
// arrive long after document_idle, so when this runs there's often nothing to
// decorate yet. Watching the whole body catches all of it.
const observer = new MutationObserver(schedule);

// Footable shows and hides columns on resize by changing their style, which
// the observer above never hears about — and it does so on a short delay of
// its own, so this waits for it before deciding which cell a badge goes in.
let resized = 0;
function onResize(): void {
  window.clearTimeout(resized);
  resized = window.setTimeout(schedule, 300);
}

if (!world[LOADED]) {
  world[LOADED] = true;
  document.addEventListener('click', rememberDetail, true);
  observer.observe(document.body, { childList: true, subtree: true });
  addEventListener('resize', onResize);
  schedule();
}
