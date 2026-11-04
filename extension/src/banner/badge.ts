import type { Section } from './messages';

/** A custom element rather than a span: Banner's stylesheet has no rules for a
 *  tag it has never heard of, so nothing of the page's lands on the host. */
export const BADGE_TAG = 'rmh-badge';

/** The site's base URL, as in api.ts. Importing it from there would inline the
 *  popup's code into content.js, since the IIFE build can't split chunks. */
const SITE = 'https://ratemyhusky.com';

/** Lives in the badge's shadow root, so the grid's CSS can't restyle it and
 *  none of this can reach the grid. Light only, because Banner is.
 *
 *  `all: initial` because a shadow root still inherits: the title cell is
 *  `white-space: nowrap; overflow: hidden`, and that came straight through and
 *  cut long names off mid-letter.
 *
 *  Wraps rather than squeezing. Once footable's expand arrow takes its share,
 *  the title cell leaves the badge roughly 85–125px. Kept to one line, the
 *  name was the only part that could give way, and in the narrower cells it
 *  gave way entirely — the badge read "★ 3.8 (49)" with nobody attached. Now
 *  the rating drops to a second line instead, and the name only ellipsizes if
 *  it's wider than the whole cell. */
const STYLE = `
  :host { all: initial; display: block; margin-top: 4px; }
  .badge {
    display: inline-flex; flex-wrap: wrap; align-items: center; gap: 0 4px;
    max-width: 100%; box-sizing: border-box; padding: 1px 7px;
    border: 1px solid #f2ccd1; border-radius: 6px; background: #fdf2f3;
    color: #16181d; font: 600 11px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    text-decoration: none;
  }
  .badge > * { flex: none; white-space: nowrap; }
  .badge > .name { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  a.badge:hover { border-color: #d6394c; }
  a.badge:focus-visible { outline: 2px solid #d6394c; outline-offset: 1px; }
  .plain { border-color: #dfe2e8; background: #f6f7f9; color: #686d78; font-weight: 400; }
  .star { color: #d99a00; }
  .quiet { color: #686d78; font-weight: 400; }
  .sample {
    padding: 0 3px; border-radius: 3px; background: #686d78; color: #fff;
    font-size: 8px; font-weight: 700; text-transform: uppercase;
  }
`;

const plural = (n: number, one: string) => (n === 1 ? one : `${one}s`);

/** Banner spells names "Last, First". */
const surname = (name: string) => name.split(',')[0].trim() || name;

function span(className: string, text: string): HTMLSpanElement {
  const el = document.createElement('span');
  el.className = className;
  el.textContent = text;
  return el;
}

/** A name and nothing claimed about it, for when the matcher abstained. */
function plain(instructor: string): HTMLElement {
  const el = span('badge plain', '');
  el.title = instructor;
  el.append(span('name', instructor));
  return el;
}

/** Built with textContent throughout, never innerHTML: the names come from a
 *  scrape of someone else's site. */
function linked(s: Section, slug: string, instructor: string, withName: boolean): HTMLElement {
  const a = document.createElement('a');
  a.className = 'badge';
  a.href = `${SITE}/professors/${encodeURIComponent(slug)}`;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.title = instructor;
  // Surname only, which keeps "Rachlin ★ 4.6 (52)" to one line in a cell
  // that can hold it. The full name is in the label and on hover.
  if (withName) a.append(span('name', surname(instructor)));

  if (s.rating != null) {
    const score = s.rating.toFixed(1);
    // "(52)" rather than "52 ratings" to keep to one line; the label below
    // spells it out for screen readers.
    a.append(span('star', `★ ${score}`), span('quiet', `(${s.numRatings})`));
    a.setAttribute(
      'aria-label',
      `${instructor}, rated ${score} out of 5 from ${s.numRatings} ${plural(s.numRatings, 'rating')} on RateMyHusky`,
    );
  } else {
    a.append(span('quiet', 'no ratings'));
    a.setAttribute('aria-label', `${instructor} on RateMyHusky, no ratings yet`);
  }
  return a;
}

export type Placement = {
  /** Built from fixture data. In the Instructor cell a badge sits under a real
   *  professor's name, so an invented rating there would read, in any
   *  screenshot, as that professor's real score. */
  sample: boolean;
  inInstructorCell: boolean;
  /** More than one name in the Instructor cell, so the badge has to say whose
   *  rating it is. */
  coTaught: boolean;
};

/** One section's badge, or null when there's nothing to say — the CRN isn't
 *  in our data, no instructor is on record for it, or the only thing to add is
 *  a name the cell already shows. */
export function badgeFor(section: Section | null, key: string, where: Placement): HTMLElement | null {
  const instructor = section?.instructor;
  if (!section || !instructor) return null;
  // No slug means the matcher abstained. Under the title the name still says
  // something the grid doesn't; in the Instructor cell Banner just said it.
  if (!section.slug && where.inInstructorCell) return null;

  const host = document.createElement(BADGE_TAG);
  host.setAttribute('data-key', key);
  // The row's own click handler opens footable's detail row and selects the
  // row. A click on the badge is ours, so it stops here — the link still
  // opens, since nothing prevents the default.
  host.addEventListener('click', (e) => e.stopPropagation());

  const style = document.createElement('style');
  style.textContent = STYLE;
  // Banner has just printed the name above a badge in the Instructor cell,
  // so the badge leaves it off — unless there's more than one name there.
  const body = section.slug
    ? linked(section, section.slug, instructor, !where.inInstructorCell || where.coTaught)
    : plain(instructor);
  if (where.sample) body.append(span('sample', 'sample'));

  host.attachShadow({ mode: 'open' }).append(style, body);
  return host;
}
