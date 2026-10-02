const API_BASE = import.meta.env.VITE_API_URL || "";

/* ---- Types ---- */
export interface Stat {
  label: string;
  value: string;
}

export interface Professor {
  name: string;
  dept: string;
  rmpRating: number | null;
  avgRating: number;
  /** Ratings behind avgRating: what the leaderboard's floor gates on and the ranking weights by. */
  totalReviews?: number;
  /** Written reviews. Unused by the leaderboard. */
  totalComments?: number;
}

export interface RandomProfessor {
  name: string;
  dept: string;
  college: string;
}

/* ---- Professor page (/full, version 2) ----
   `summary` holds the blended numbers every page shows; `sources.<name>` holds what
   each source measured; `courses` has one row per course the ratings name. */

export interface ProfessorIdentity {
  slug: string;
  name: string;
  department: string;
  college: string | null;
  imageUrl: string | null;
  focusX: number;
  focusY: number;
}

export interface SourceSummary {
  rating: number | null;
  numRatings: number;
}

export interface ProfessorSummary {
  rating: number | null;
  difficulty: number | null;
  wouldTakeAgainPct: number | null;
  numRatings: number;
  numComments: number;
  hoursPerWeek: number | null;
  bySource: Record<string, SourceSummary>;
}

export type RatingDistribution = Record<'1' | '2' | '3' | '4' | '5', number>;

export interface RmpData {
  /** False without RMP ratings; every number below is null then. */
  available: boolean;
  rating: number | null;
  difficulty: number | null;
  wouldTakeAgainPct: number | null;
  numRatings: number;
  professorUrl: string | null;
  ratingDistribution: RatingDistribution;
  gradeDistribution: Record<string, number>;
  reviews: ProfessorReview[];
}

export interface ProfessorCourse {
  code: string;
  /** null when the code is not in the course catalog (no course page to link to). */
  name: string | null;
  rating: number | null;
  difficulty: number | null;
  numRatings: number;
  ratingDistribution: RatingDistribution;
  /** Terms taught. Not sent yet: it arrives with student-submitted data, and no term tags show until then. */
  terms?: string[];
}

export interface ProfessorPage {
  version: 2;
  identity: ProfessorIdentity;
  summary: ProfessorSummary;
  sources: { rmp: RmpData };
  courses: ProfessorCourse[];
  redditMentions: RedditMention[];
}

export interface ProfessorReview {
  course: string;
  quality: number;
  difficulty: number;
  date: string;
  tags: string;
  attendance: string;
  grade: string;
  textbook: string;
  online_class: string;
  comment: string;
}

export interface RedditMention {
  body: string;
  sentiment: 'positive' | 'neutral' | 'negative' | null;
  sentiment_score: number | null;  // signed -1..+1 (negative=left, 0=neutral, positive=right)
  score: number | null;
  subreddit: string | null;
  permalink: string | null;
  created_utc: string | null;  // RFC-822 timestamp string from the backend (TIMESTAMPTZ → jsonify)
}

/* ---- Session caches (cleared on page refresh, keyed by slug/code) ---- */
const _courseCache = new Map<string, CourseDetail>();

const _profPageCache = new Map<string, ProfessorPage>();

/* ---- Maintenance detection ----
   While maintenance mode is on, Vercel 307-redirects /api/* to
   /maintenance.html and fetch() follows it silently. If that happened,
   send this tab to the maintenance page and report true so callers bail. */
export function maintenanceGuard(res: Response): boolean {
  if (res.redirected && new URL(res.url).pathname === '/maintenance.html') {
    window.location.replace('/maintenance.html');
    return true;
  }
  return false;
}

/* ---- Fetchers ---- */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/* A fetch that reports why it failed, so a page shows NotFound only for a real 404.
   status 0 = network failure or the maintenance redirect. */
export type Fetched<T> = { ok: true; data: T } | { ok: false; status: number };

async function fetchWithStatus<T>(path: string): Promise<Fetched<T>> {
  try {
    return { ok: true, data: await get<T>(path) };
  } catch (e) {
    return { ok: false, status: e instanceof ApiError ? e.status : 0 };
  }
}

async function get<T>(path: string): Promise<T> {
  const headers: Record<string, string> = {};
  const token = localStorage.getItem('auth_token');
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { headers, cache: token ? 'no-cache' : 'default' });
  if (maintenanceGuard(res)) throw new Error('Site is under maintenance');
  if (!res.ok) throw new ApiError(res.status, `API ${res.status}: ${res.statusText}`);
  return res.json();
}

export const fetchStats = () => get<Stat[]>("/api/stats");

export const fetchColleges = () => get<string[]>("/api/colleges");

export const fetchGoatProfessors = (college: string, limit = 10) =>
  get<Professor[]>(`/api/goat-professors?college=${encodeURIComponent(college)}&limit=${limit}`);

export const fetchRandomProfessor = () => get<RandomProfessor>("/api/random-professor");

/* ---- Professor page fetchers ---- */
/* The Professor page's single round-trip. Every visitor gets the same payload, so the
   cache is keyed by slug alone; failures are not cached. */
export async function fetchProfessorFull(slug: string): Promise<Fetched<ProfessorPage>> {
  const cached = _profPageCache.get(slug);
  if (cached) return { ok: true, data: cached };
  const res = await fetchWithStatus<ProfessorPage>(`/api/professors/${encodeURIComponent(slug)}/full`);
  if (res.ok) _profPageCache.set(slug, res.data);
  return res;
}

/* ---- Search autocomplete ---- */
export interface ProfessorSuggestion {
  type: "professor";
  name: string;
  dept: string;
  rating: number | null;
  slug: string;
}

export interface CourseSuggestion {
  type: "course";
  code: string;
  name: string;
  dept: string;
}

export type SearchSuggestion = ProfessorSuggestion | CourseSuggestion;

export const fetchSearchSuggestions = (query: string, type: string) =>
  get<SearchSuggestion[]>(`/api/search?q=${encodeURIComponent(query)}&type=${encodeURIComponent(type)}`);

/* ---- Ask mode (Reddit RAG question path) ---- */
export interface ChatSource {
  source_id: number;
  snippet: string;
  permalink: string;
  subreddit: string;
  professor_slug?: string | null;
  course_code?: string | null;
  source?: string | null;
}

export interface ChatProfessorMatch {
  name: string;
  department: string;
}

export type ChatResponse =
  | { mode: 'question'; answer: string; sources: ChatSource[]; cited?: number[]; professor_slug: string; course_code: string | null; disclaimer: string; entities?: { name: string; professor_slug?: string | null; course_code?: string | null }[] }
  | { mode: 'disambiguation'; message: string; matches: ChatProfessorMatch[] }
  | { mode: 'out_of_scope' | 'thin_data' | 'keyword'; banner?: string; message?: string; comments: unknown[]; professors: unknown[] }
  | { mode: 'course_list'; answer: string; topic?: string;
      courses: { code: string; name: string; department?: string; rating?: number | null }[];
      disclaimer: string }
  | { mode: 'error'; message: string };

/* Ask does its own fetch instead of get<T>(): get() throws on any non-2xx, but Ask must read
   the 401 body and the various 200 modes. Returns a synthetic error on network failure so the
   caller never has to try/catch. */
export async function askChat(q: string): Promise<{ status: number; body: ChatResponse }> {
  const headers: Record<string, string> = {};
  const token = localStorage.getItem('auth_token');
  if (token) headers['Authorization'] = `Bearer ${token}`;
  try {
    const res = await fetch(`${API_BASE}/api/chat?mode=question&q=${encodeURIComponent(q)}`, {
      headers,
      cache: 'no-cache',
    });
    if (maintenanceGuard(res)) throw new Error('Site is under maintenance');
    const body = (await res.json()) as ChatResponse;
    return { status: res.status, body };
  } catch {
    return { status: 0, body: { mode: 'error', message: 'Something went wrong — try again.' } };
  }
}

/* ---- Professor catalog (browse page) ---- */
export interface CatalogProfessor {
  name: string;
  slug: string;
  department: string;
  college: string;
  avgRating: number | null;
  rmpRating: number | null;
  totalReviews: number;
  totalComments: number;
  wouldTakeAgainPct: number | null;
  imageUrl: string | null;
  focusX: number;
  focusY: number;
}

export interface CatalogResponse {
  professors: CatalogProfessor[];
  total: number;
  page: number;
  totalPages: number;
}

export interface CatalogCourse {
  code: string;
  name: string;
  department: string;
  avgRating: number | null;
}

export interface CourseCatalogResponse {
  courses: CatalogCourse[];
  total: number;
  page: number;
  totalPages: number;
}

export interface CourseSummary {
  rating: number | null;
  difficulty: number | null;
  numRatings: number;
  hoursPerWeek: number | null;
  bySource: Record<string, SourceSummary>;
}

export interface CourseProfessor {
  slug: string;
  name: string;
  imageUrl: string | null;
  focusX: number;
  focusY: number;
  /** This professor's ratings for this course only. */
  rating: number | null;
  difficulty: number | null;
  numRatings: number;
}

export interface CourseDetail {
  code: string;
  name: string;
  department: string;
  catalog: null;
  summary: CourseSummary;
  professors: CourseProfessor[];
}

export function fetchProfessorsCatalog(params: {
  q?: string;
  college?: string;
  dept?: string;
  minRating?: number;
  maxRating?: number;
  minReviews?: number;
  maxReviews?: number;
  sort?: 'alpha' | 'rating' | 'comments';
  page?: number;
  limit?: number;
}): Promise<CatalogResponse> {
  const sp = new URLSearchParams();
  if (params.q) sp.set('q', params.q);
  if (params.college) sp.set('college', params.college);
  if (params.dept) sp.set('dept', params.dept);
  if (params.minRating) sp.set('minRating', String(params.minRating));
  if (params.maxRating !== undefined && params.maxRating < 5) sp.set('maxRating', String(params.maxRating));
  if (params.minReviews) sp.set('minReviews', String(params.minReviews));
  if (params.maxReviews !== undefined) sp.set('maxReviews', String(params.maxReviews));
  if (params.sort) sp.set('sort', params.sort);
  if (params.page) sp.set('page', String(params.page));
  if (params.limit) sp.set('limit', String(params.limit));
  return get<CatalogResponse>(`/api/professors-catalog?${sp.toString()}`);
}

/** Joins multi-select dept/college filter values. Not ",": department names
 *  carry commas ("Lang, Literature and Culture"). Must match FILTER_SEPARATOR
 *  in backend/server.py. */
export const FILTER_SEPARATOR = '|';

export const fetchDepartments = (college?: string) => {
  const sp = new URLSearchParams();
  if (college) sp.set('college', college);
  return get<string[]>(`/api/departments?${sp.toString()}`);
};

export const fetchCourseDepartments = () => get<string[]>('/api/course-departments');

export function fetchCoursesCatalog(params: {
  q?: string;
  dept?: string;
  minRating?: number;
  maxRating?: number;
  sort?: 'alpha' | 'rating' | 'sections' | 'recent';
  page?: number;
  limit?: number;
}): Promise<CourseCatalogResponse> {
  const sp = new URLSearchParams();
  if (params.q) sp.set('q', params.q);
  if (params.dept) sp.set('dept', params.dept);
  if (params.minRating) sp.set('minRating', String(params.minRating));
  if (params.maxRating !== undefined && params.maxRating < 5) sp.set('maxRating', String(params.maxRating));
  if (params.sort) sp.set('sort', params.sort);
  if (params.page) sp.set('page', String(params.page));
  if (params.limit) sp.set('limit', String(params.limit));
  return get<CourseCatalogResponse>(`/api/courses-catalog?${sp.toString()}`);
}

export async function submitFeedback(payload: {
  feedbackType: string;
  description: string;
  email?: string;
  turnstileToken?: string;
  accountSub?: string;
}): Promise<void> {
  const res = await fetch(`${API_BASE}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (maintenanceGuard(res)) throw new Error("Site is under maintenance");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `API ${res.status}`);
  }
}

/* ---- Bookmarks ---- */
export interface BookmarksResponse {
  professors: (CatalogProfessor & { bookmarkedAt: string })[];
  courses: (CatalogCourse & { bookmarkedAt: string })[];
}

export const fetchBookmarks = () => get<BookmarksResponse>('/api/bookmarks');

function bookmarkAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('auth_token');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function addBookmark(itemType: 'professor' | 'course', itemKey: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/bookmarks`, {
    method: 'POST',
    headers: bookmarkAuthHeaders(),
    body: JSON.stringify({ itemType, itemKey }),
  });
  if (maintenanceGuard(res)) throw new Error('Site is under maintenance');
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `API ${res.status}`);
  }
}

export async function removeBookmark(itemType: 'professor' | 'course', itemKey: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/bookmarks`, {
    method: 'DELETE',
    headers: bookmarkAuthHeaders(),
    body: JSON.stringify({ itemType, itemKey }),
  });
  if (maintenanceGuard(res)) throw new Error('Site is under maintenance');
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `API ${res.status}`);
  }
}

/* ---- Department hub pages ---- */
export interface HubDepartment {
  slug: string;
  name: string;
  professorCount: number;
  avgRating: number | null;
}

export interface DepartmentsHubResponse {
  departments: HubDepartment[];
  total: number;
}

export const fetchDepartmentsHub = () => get<DepartmentsHubResponse>('/api/departments/hub');

export interface DepartmentProfessor {
  name: string;
  slug: string | null;
  avgRating: number | null;
  difficulty: number | null;
  wouldTakeAgainPct: number | null;
  totalRatings: number;
}

export interface DepartmentDetail {
  name: string;
  slug: string;
  professorCount: number;
  avgRating: number | null;
  professors: DepartmentProfessor[];
}

export async function fetchDepartmentDetail(slug: string): Promise<DepartmentDetail | null> {
  try {
    return await get<DepartmentDetail>(`/api/departments/${encodeURIComponent(slug)}`);
  } catch {
    return null;
  }
}

/* Same payload for every visitor, so cached by code alone; failures are not cached. */
export async function fetchCourseData(code: string): Promise<Fetched<CourseDetail>> {
  const cached = _courseCache.get(code);
  if (cached) return { ok: true, data: cached };
  const res = await fetchWithStatus<CourseDetail>(`/api/courses/${encodeURIComponent(code)}`);
  if (res.ok) _courseCache.set(code, res.data);
  return res;
}