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
  a.plain:hover { border-color: #b9bec8; }
  .star { color: #d99a00; }
  .quiet { color: #686d78; font-weight: 400; }
  .sample {
    padding: 0 3px; border-radius: 3px; background: #686d78; color: #fff;
    font-size: 8px; font-weight: 700; text-transform: uppercase;
  }
  .pending {
    display: block; width: 72px; height: 16px; border-radius: 6px;
    background: linear-gradient(90deg, #f1f2f4 0%, #e3e5e9 50%, #f1f2f4 100%);
    background-size: 200% 100%; animation: rmh-shimmer 1.2s ease-in-out infinite;
  }
  @keyframes rmh-shimmer { from { background-position: 100% 0; } to { background-position: -100% 0; } }
  @media (prefers-reduced-motion: reduce) { .pending { animation: none; } }
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

/** For an instructor we couldn't match to a professor page. Nothing is claimed
 *  about them — no rating, no guess — just a way to be the first to rate them,
 *  since a gap here is usually a professor nobody's added yet. Under the title
 *  the name comes too, because the grid there doesn't show one. */
function unmatched(instructor: string, withName: boolean): HTMLElement {
  const a = document.createElement('a');
  a.className = 'badge plain';
  a.href = `${SITE}/rate`;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.title = `${instructor} isn't on RateMyHusky yet`;
  if (withName) a.append(span('name', surname(instructor)));
  a.append(span('quiet', 'Rate this professor'));
  a.setAttribute('aria-label', `Rate ${instructor} on RateMyHusky; no ratings yet`);
  return a;
}

/** Built with textContent throughout, never innerHTML: the names come from a
 *  scrape of someone else's site. */
function linked(s: Section, slug: string, instructor: string, withName: boolean): HTMLElement {
  const a = document.createElement('a');
  a.className = 'badge';
  a.href = `${SITE}/professors/${encodeURIComponent(slug)}`;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  // Says what a click does, since it opens the popup rather than following
  // the link. The full name rides along, as the badge may show only the
  // surname.
  a.title = `Open ${instructor} in RateMyHusky`;
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
  /** A plain click opens the professor in the popup instead of the site. */
  onOpen?: () => void;
};

/** One section's badge, or null when there's nothing to say — the CRN isn't
 *  in our data, or no instructor is on record for it. */
export function badgeFor(section: Section | null, key: string, where: Placement): HTMLElement | null {
  const instructor = section?.instructor;
  if (!section || !instructor) return null;

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
    : unmatched(instructor, !where.inInstructorCell || where.coTaught);
  if (where.sample) body.append(span('sample', 'sample'));

  // Only a plain left click is taken over. Cmd/Ctrl/Shift-click and the
  // middle button still do what a link does, so the site stays one gesture
  // away — and the href is what opens if the popup can't.
  if (section.slug && where.onOpen && !where.sample) {
    const open = where.onOpen;
    body.addEventListener('click', (e) => {
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      open();
    });
  }

  const shadow = host.attachShadow({ mode: 'open' });
  shadow.append(style, body);
  return host;
}

/** Holds a row's place while its lookup is in flight, so a slow connection
 *  reads as loading rather than as a row with nothing to show. Replaced by
 *  the real badge, or removed, when the answer lands. */
export function pendingBadge(key: string): HTMLElement {
  const host = document.createElement(BADGE_TAG);
  host.setAttribute('data-key', key);
  host.setAttribute('aria-hidden', 'true');
  const style = document.createElement('style');
  style.textContent = STYLE;
  host.attachShadow({ mode: 'open' }).append(style, span('pending', ''));
  return host;
}
