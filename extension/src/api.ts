import searchFixture from './fixtures/search.json';

// Flip once the site is out of maintenance and /api/* returns JSON again.
export const USE_FIXTURES = false;

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

export type ProfessorReview = {
  id?: string | number;
  course: string;
  courseCode: string | null;
  quality: number;
  difficulty: number;
  date: string;
  tags: string;
  comment: string;
};

export type ProfessorProfile = {
  identity: {
    slug: string;
    name: string;
    department: string;
    imageUrl: string | null;
  };
  summary: {
    rating: number | null;
    numRatings: number;
    numComments: number;
  };
  sources: {
    rmp: { reviews: ProfessorReview[]; numRatings: number };
    survey: {
      available: boolean;
      rating: number | null;
      numRatings: number;
      ratingDistribution: Record<'1' | '2' | '3' | '4' | '5', number>;
    };
  };
};

export type Suggestion = ProfessorSuggestion | CourseSuggestion;

const MAINTENANCE_PATH = '/maintenance.html';

/** The site is unreachable: maintenance, or no network. Anything else — a 403
 *  from an origin that isn't allowlisted, a 429, a 500 — is a real error and
 *  must not be reported as maintenance. */
class Unavailable extends Error {}

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
    const tokens = q.toLowerCase().split(/\s+/).filter(Boolean);
    return (searchFixture as Suggestion[])
      .filter((s): s is ProfessorSuggestion => s.type === 'professor')
      .filter((s) => {
        const nameTokens = s.name.toLowerCase().split(/\s+/);
        return tokens.every((token) =>
          nameTokens.some(
            (nameToken) => nameToken.startsWith(token),
          ),
        );
      })
      .slice(0, limit);
  }

  return get<ProfessorSuggestion[]>(
    `/api/search?q=${encodeURIComponent(q)}&type=Professor&limit=${limit}`,
  );
}

export async function fetchProfessorProfile(slug: string): Promise<ProfessorProfile> {
  return get<ProfessorProfile>(`/api/professors/${encodeURIComponent(slug)}/full`);
}

export function isUnavailable(err: unknown): boolean {
  return err instanceof Unavailable;
}

export function professorUrl(slug: string): string {
  return `${API_BASE}/professors/${encodeURIComponent(slug)}`;
}
