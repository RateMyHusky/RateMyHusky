// The extension launch video: one entry per clip, in order.
// Clips are 1920x1080, cut from one screen recording with ffmpeg (trimmed,
// cropped clear of Banner's account name and Chrome's address bar, and sped
// up to exactly `frames` long), and live in promo/public/extension/, which is
// gitignored. A clip that isn't there renders as a card showing its `record`
// note, so the video previews before anything's filmed.

export type Shot = {
  id: string;
  file: string;
  caption: string;
  /** What to film, shown on the placeholder card. */
  record: string;
  /** Length of the slot in frames at 30fps. The clip is cut to match. */
  frames: number;
  /** Where the slow push-in heads, as CSS transform-origin: the part of the
   *  frame the viewer should be looking at. */
  focus: string;
};

export const SHOTS: Shot[] = [
  {
    id: 'badges',
    file: 'extension/badges.mp4',
    caption: 'See ratings while you pick classes',
    record: 'Banner class search loading: the shimmer turns into rating badges in the Instructor column.',
    frames: 100,
    focus: '50% 60%',
  },
  {
    id: 'sort',
    file: 'extension/sort.mp4',
    caption: 'Every section, rated at a glance',
    record: 'Click a column header to re-sort the results. Badges move with their rows.',
    frames: 105,
    focus: '45% 55%',
  },
  {
    id: 'open',
    file: 'extension/open.mp4',
    caption: "Know who you're signing up for",
    record: 'Click a rating badge. The RateMyHusky popup opens on that professor.',
    frames: 120,
    focus: '80% 30%',
  },
  {
    id: 'reviews',
    file: 'extension/reviews.mp4',
    caption: 'Read real reviews before you register',
    record: 'In the popup: View Reviews, scroll a little, switch the sort to Highest.',
    frames: 150,
    focus: '80% 35%',
  },
  {
    id: 'compare',
    file: 'extension/compare.mp4',
    caption: 'Torn between sections? Compare them',
    record: 'Overview → Compare → search and pick a second professor. End on the side-by-side table.',
    frames: 165,
    focus: '80% 30%',
  },
  {
    id: 'search',
    file: 'extension/search.mp4',
    caption: 'Save your picks for registration day',
    record: 'Overview → tap the bookmark → back to Search, where Saved lists them.',
    frames: 120,
    focus: '80% 30%',
  },
];

/** Opens on the problem before the product: registration week means juggling
 *  Banner and a pile of rating tabs. */
export const HOOK_FRAMES = 75;
// A no-break space keeps "20 tabs" on one line when the sentence wraps.
export const HOOK = 'Registration week shouldn’t take 20\u00a0tabs.';
export const INTRO_FRAMES = 80;
export const OUTRO_FRAMES = 100;
export const TRANSITION_FRAMES = 10;

export const TOTAL_FRAMES =
  HOOK_FRAMES +
  INTRO_FRAMES +
  OUTRO_FRAMES +
  SHOTS.reduce((sum, s) => sum + s.frames, 0) -
  (SHOTS.length + 2) * TRANSITION_FRAMES;

export const TAGLINE = 'Course registration, made easier.';
export const CTA = 'Register smarter. Add RateMyHusky to Chrome.';
