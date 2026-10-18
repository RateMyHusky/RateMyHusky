import searchFixture from './fixtures/search.json';
import professorFixture from './fixtures/professor.json';

// Flip once the site is out of maintenance and /api/* returns JSON again.
export const USE_FIXTURES = true;

// Must be the site, not the backend host: the API only accepts traffic
// proxied through here, which is what attaches the shared secret.
const API_BASE = 'https://ratemyhusky.com';

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

export function isUnavailable(err: unknown): boolean {
  return err instanceof Unavailable;
}

export function isNotFound(err: unknown): boolean {
  return err instanceof NotFound;
}

export function professorUrl(slug: string): string {
  return `${API_BASE}/professors/${encodeURIComponent(slug)}`;
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
  courses: { code: string; name: string | null; hasPage: boolean }[];
  lastTaught: string | null;
  awards: TeachingAward[];
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

export async function fetchProfessor(slug: string): Promise<Professor> {
  if (USE_FIXTURES) {
    // One professor is captured. Returning them for every slug would make
    // every search result open the same page once search is wired up.
    if (slug !== professorFixture.identity.slug) {
      throw new NotFound(`no fixture for ${slug}`);
    }
    return professorFixture as Professor;
  }
  return get<Professor>(`/api/professors/${encodeURIComponent(slug)}/full`);
}
