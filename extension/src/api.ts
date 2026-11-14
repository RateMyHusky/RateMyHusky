import searchFixture from './fixtures/search.json';
import rachlin from './fixtures/professors/john-rachlin.json';
import kaeli from './fixtures/professors/david-kaeli.json';

// Keyed by slug so fixture mode behaves like the real API: a slug we captured
// resolves, anything else 404s. Add a file and a line here to capture more.
const PROFESSOR_FIXTURES: Record<string, unknown> = {
  'john-rachlin': rachlin,
  'david-kaeli': kaeli,
};

// Live by default. Set true to work offline, or while the site is in
// maintenance and /api/* serves the maintenance page instead of JSON.
export const USE_FIXTURES = false;

// Must be the site, not the backend host: the API only accepts traffic
// proxied through here, which is what attaches the shared secret.
export const SITE_URL = 'https://ratemyhusky.com';
const API_BASE = SITE_URL;

export type ProfessorSuggestion = {
  type: 'professor';
  name: string;
  dept: string | null;
  rating: number | null;
  slug: string;
};

export type CourseSuggestion = {
  type: 'course';
  code: string;
  name: string | null;
  dept: string | null;
};

export type Suggestion = ProfessorSuggestion | CourseSuggestion;

const MAINTENANCE_PATH = '/maintenance.html';

/** The site is unreachable: maintenance, or no network. Anything else — a 403
 *  from an origin that isn't allowlisted, a 429, a 500 — is a real error and
 *  must not be reported as maintenance. */
class Unavailable extends Error {}

/** The slug doesn't resolve. A missing professor is not a broken extension. */
class NotFound extends Error {}

async function get<T>(path: string): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, { credentials: 'omit' });
  } catch (err) {
    throw new Unavailable(`network error: ${(err as Error).message}`);
  }

  // Maintenance is a 307 to /maintenance.html, which then serves 200 HTML —
  // never a 503. fetch follows the redirect, so the landing url is the signal.
  if (resp.redirected && new URL(resp.url).pathname === MAINTENANCE_PATH) {
    throw new Unavailable('site is in maintenance');
  }

  if (resp.status === 404) throw new NotFound(`${resp.status} ${resp.statusText}`);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);

  const text = await resp.text();
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Unavailable('expected JSON, got a page');
  }
}

export async function searchProfessors(
  query: string,
  limit = 5,
): Promise<ProfessorSuggestion[]> {
  const q = query.trim();
  if (q.length < 2) return [];

  if (USE_FIXTURES) {
    const needle = q.toLowerCase();
    return (searchFixture as Suggestion[])
      .filter((s): s is ProfessorSuggestion => s.type === 'professor')
      .filter((s) => s.name.toLowerCase().includes(needle))
      .slice(0, limit);
  }

  return get<ProfessorSuggestion[]>(
    `/api/search?q=${encodeURIComponent(q)}&type=Professor&limit=${limit}`,
  );
}

/** Every screen turns a failed fetch into the same three sentences. Keeping
 *  that here means the next case — a 429, say — is added once rather than in
 *  Overview, Compare and Courses separately. */
export function errorMessage(err: unknown): string {
  if (err instanceof NotFound) return 'Professor not found.';
  if (err instanceof Unavailable) return "Can't reach RateMyHusky right now.";
  return 'Something went wrong.';
}

export function professorUrl(slug: string): string {
  return `${API_BASE}/professors/${encodeURIComponent(slug)}`;
}

export function courseUrl(code: string): string {
  return `${SITE_URL}/courses/${encodeURIComponent(code)}`;
}

/** Scraped URLs only become links if they're absolute http(s). A javascript:
 *  or data: URL in the data would otherwise turn into a clickable href; MV3's
 *  CSP should stop it running, but scraped data shouldn't lean on that. Same
 *  rule as safeRedditUrl on the site's professor page. */
export function safeHttpUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    return ['http:', 'https:'].includes(new URL(url).protocol) ? url : undefined;
  } catch {
    return undefined;
  }
}

export type Professor = {
  version: number;
  identity: {
    slug: string;
    name: string;
    department: string | null;
    college: string | null;
    imageUrl: string | null;
    focusX: number;
    focusY: number;
  };
  summary: {
    rating: number | null;
    difficulty: number | null;
    wouldTakeAgainPct: number | null;
    numRatings: number;
    numComments: number;
    hoursPerWeek: number | null; // always null — no source provides it
  };
  courses: Course[];
  lastTaught: string | null;
  awards: TeachingAward[];
};

/** Banner history keeps only this many terms per course (`labels[:6]` in
 *  scraper/banner_history.py), so a course at the cap may have been taught
 *  more often than its list shows. */
export const RECENT_TERMS_CAP = 6;

export type Course = {
  code: string;
  name: string | null;
  hasPage: boolean;
  /** The most recent terms it was taught, newest first — at most
   *  RECENT_TERMS_CAP, not every term on record. Empty when Banner has no
   *  history for the course at all. */
  terms: string[];
  lastTerm: string | null;
  numRatings: number;
  rating: number | null;
};

/** Same shape as TeachingAward in frontend/src/api/api.ts. */
export type TeachingAward = {
  award: string;
  awardingBody: string;
  year: number;
  /** As the source prints it: "2022–23" for an academic year, "2024" for Khoury's. */
  yearLabel: string;
  sourceUrl: string;
};

/** One request per professor for as long as the popup is open. Every screen
 *  fetches on mount and the view stack unmounts whatever is underneath, so
 *  Overview → Courses → Back was downloading the same /full three times. The
 *  popup lives for seconds; nothing goes stale in that time. */
const professors = new Map<string, Promise<Professor>>();

export function fetchProfessor(slug: string): Promise<Professor> {
  const cached = professors.get(slug);
  if (cached) return cached;

  const pending = loadProfessor(slug);
  professors.set(slug, pending);
  // A failure leaves the cache, so the next visit retries instead of
  // replaying the same error.
  pending.catch(() => professors.delete(slug));
  return pending;
}

async function loadProfessor(slug: string): Promise<Professor> {
  if (USE_FIXTURES) {
    // hasOwn, not a truthiness check: the fixtures are a plain object, so
    // "constructor" or "toString" came back as a Professor and crashed the
    // screen instead of 404ing. Matters once the slug comes from a search.
    if (!Object.hasOwn(PROFESSOR_FIXTURES, slug)) throw new NotFound(`no fixture for ${slug}`);
    return PROFESSOR_FIXTURES[slug] as Professor;
  }
  return get<Professor>(`/api/professors/${encodeURIComponent(slug)}/full`);
}
