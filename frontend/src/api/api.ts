const API_BASE = import.meta.env.VITE_API_URL || "";

/* ---- Types ---- */
export interface Stat {
  label: string;
  value: string;
}

export interface Professor {
  slug: string;
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
  /** The department's /departments page, or null when it has none (no rated professors, or another spelling holds the slug). */
  departmentSlug?: string | null;
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

export interface SurveyData {
  /** False without survey ratings; every number below is null then. */
  available: boolean;
  rating: number | null;
  numRatings: number;
  hoursPerWeek: number | null;
  ratingDistribution: RatingDistribution;
  gradeDistribution: Record<string, number>;
  /** Accepted /rate comments, newest first, at most 200. Never carries the grade.
   *  Missing from a /full cached before it shipped. */
  reviews?: SurveyReview[];
}

export interface SurveyReview {
  /** A keyed hash, not the row id: for anchors and reports. */
  id: string;
  course: string | null;
  /** "Fall 2025" when the class was big enough to show the term, else the year when the
   *  professor taught the course in 2+ terms that year, else "" (no date shown). */
  when: string;
  rating: number;
  comment: string;
}

export interface ProfessorCourse {
  code: string;
  /** The catalog name, else Banner's title. null when neither has one. */
  name: string | null;
  /** null on a course Banner says they taught but no one has rated. */
  rating: number | null;
  difficulty: number | null;
  /** 0 on a Banner-only course. */
  numRatings: number;
  ratingDistribution: RatingDistribution | null;
  /** Terms they taught it, newest first, at most 6 (NUBanner, Fall 2021 on). Empty without a Banner record. */
  terms: string[];
  lastTerm: string | null;
  /** The code has a course page to link to. Absent from payloads built before
   *  teaching history (deploy rollout, cached /full): fall back to `name != null`. */
  hasPage?: boolean;
}

/** A teaching award from a page Northeastern publishes; newest first. */
export interface TeachingAward {
  award: string;
  /** "Northeastern University" for the provost's award, else the college. */
  awardingBody: string;
  year: number;
  /** As the source prints it: "2022–23" for an academic year, "2024" for Khoury's. */
  yearLabel: string;
  sourceUrl: string;
}

export interface ProfessorPage {
  version: 2;
  identity: ProfessorIdentity;
  summary: ProfessorSummary;
  sources: { rmp: RmpData; survey: SurveyData };
  courses: ProfessorCourse[];
  redditMentions: RedditMention[];
  awards: TeachingAward[];
  /** The newest term Banner has them teaching; null when unknown (most instructors have no profile match). */
  lastTaught: string | null;
}

export interface ProfessorReview {
  course: string;
  courseCode: string | null;
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
/* Pages this tab just rated: the next /full skips the browser's HTTP cache (max-age=3600),
   so the rater sees their own review instead of the copy fetched before they saved. */
const _ratedProfPages = new Set<string>();

/* ---- Maintenance detection ----
   While maintenance mode is on, Vercel 307-redirects /api/* to
   /maintenance.html and fetch() follows it silently. If that happened,
   send this tab to the maintenance page and report true so callers bail. */
export function maintenanceGuard(res: Response): boolean {
  if (res.redirected && new URL(res.url).pathname === '/maintenance.html') {
    window.location.replace(res.url); // keeps ?mode=preview on previews
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

async function fetchWithStatus<T>(path: string, signal?: AbortSignal, fresh = false): Promise<Fetched<T>> {
  try {
    return { ok: true, data: await get<T>(path, signal, fresh) };
  } catch (e) {
    return { ok: false, status: e instanceof ApiError ? e.status : 0 };
  }
}

async function get<T>(path: string, signal?: AbortSignal, fresh = false): Promise<T> {
  const headers: Record<string, string> = {};
  const token = localStorage.getItem('auth_token');
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { headers, cache: token || fresh ? 'no-cache' : 'default', signal });
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
export async function fetchProfessorFull(slug: string, signal?: AbortSignal): Promise<Fetched<ProfessorPage>> {
  const cached = _profPageCache.get(slug);
  if (cached) return { ok: true, data: cached };
  const fresh = _ratedProfPages.has(slug);
  const res = await fetchWithStatus<ProfessorPage>(`/api/professors/${encodeURIComponent(slug)}/full`, signal, fresh);
  if (res.ok) {
    _profPageCache.set(slug, res.data);
    _ratedProfPages.delete(slug);
  }
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
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem('auth_token');
  if (token) headers['Authorization'] = `Bearer ${token}`;
  try {
    // POST, not a query string, so the question stays out of server access logs.
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ q }),
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
  /** Ratings behind avgRating. Optional: the bookmarks payload doesn't carry it. */
  numRatings?: number;
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
  /** The newest term Banner has them teaching this course; null without a Banner record. */
  lastTerm: string | null;
  avgClassSize: number | null;
}

export interface CourseCatalog {
  description: string | null;
  credits: string | null;
  prerequisites: string | null;
  corequisites: string | null;
  nupath: string[];
}

/** The other end of a redesign link (CS3500 → CS3100). */
export interface HistoryCourseLink {
  code: string;
  name: string | null;
  since: string;
  /** The code has a course page to link to. */
  hasPage: boolean;
}

export interface RecentInstructor {
  /** null for an instructor with no professor profile: an initials card with no link. */
  slug: string | null;
  name: string;
  imageUrl: string | null;
  focusX: number;
  focusY: number;
  /** Their rating for this course; null when unrated. */
  rating: number | null;
  /** Terms they taught it in the last year, newest first. */
  terms: string[];
  /** Their ratings of this course: 0 with none, null when unmatched. */
  numRatings: number | null;
  /** Their catalog-wide would-take-again; null with no profile. 0% is real. */
  wouldTakeAgainPct: number | null;
}

/** NUBanner history (Fall 2021 on). The payload also carries instructors[]; the page reads recentInstructors. */
export interface CourseHistory {
  /** "Fall and Spring", "New", "Not offered recently"…; null for a retired code with only a successor link. */
  pattern: string | null;
  /** The pattern window's academic years, oldest first, keyed by the year they end (2026 is 2025–26), and
   *  the window years each season ran. first: the course's first academic year. null until the scraper stores them. */
  offeringYears: {
    window: number[];
    first: number;
    fall: number[];
    spring: number[];
    summer1: number[];
    summer2: number[];
    summer: number[];
  } | null;
  /** The oldest term Banner has it in ("Fall 2025"). */
  firstOffered: string | null;
  lastOffered: string | null;
  offeredNow: string[];
  creditHours: string | null;
  typicalClassSize: number | null;
  /** Taught it in the 12 months up to the newest term, newest first, at most 10. */
  recentInstructors: RecentInstructor[];
  replacedBy: HistoryCourseLink | null;
  replaces: HistoryCourseLink | null;
}

export interface CourseDetail {
  code: string;
  name: string;
  department: string;
  catalog: CourseCatalog | null;
  summary: CourseSummary;
  professors: CourseProfessor[];
  history: CourseHistory | null;
}

export type ProfessorSort = 'alpha' | 'alpha_desc' | 'rating' | 'rating_asc' | 'comments' | 'ratings';

export function fetchProfessorsCatalog(params: {
  q?: string;
  college?: string;
  dept?: string;
  minRating?: number;
  maxRating?: number;
  minReviews?: number;
  maxReviews?: number;
  sort?: ProfessorSort;
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

export type CourseSort = 'alpha' | 'alpha_desc' | 'rating' | 'rating_asc' | 'ratings' | 'recent';

export function fetchCoursesCatalog(params: {
  q?: string;
  dept?: string;
  minRating?: number;
  maxRating?: number;
  sort?: CourseSort | 'sections';
  page?: number;
  limit?: number;
  rated?: boolean;
}): Promise<CourseCatalogResponse> {
  const sp = new URLSearchParams();
  if (params.q) sp.set('q', params.q);
  if (params.dept) sp.set('dept', params.dept);
  if (params.minRating) sp.set('minRating', String(params.minRating));
  if (params.maxRating !== undefined && params.maxRating < 5) sp.set('maxRating', String(params.maxRating));
  if (params.sort) sp.set('sort', params.sort);
  if (params.page) sp.set('page', String(params.page));
  if (params.limit) sp.set('limit', String(params.limit));
  if (params.rated) sp.set('rated', '1');
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

/* ---- Student ratings (/rate) ---- */
export interface RateStart { opened: string; deviceToken: string; counter: number | null }
export interface RatedCourse {
  /* pending: the course is still awaiting review, so the form resends it as a new course. */
  code: string; name: string | null; pending: boolean; term: string | null;
  /* difficulty: null for a rating from before the form asked it. */
  rating: number; difficulty: number | null; hours: string; grade: string | null; comment: string;
}
export interface RateProfessorContext { ratedCourses: RatedCourse[] }
export interface RateSubmission {
  professor: { slug: string } | { name: string; department: string | null };
  course: { code: string } | { code: string; name: string };
  term: string | null;
  rating: number;
  difficulty: number;
  hours: string;
  grade: string | null;
  comment: string;
  opened: string;
  deviceToken: string | null;
  website: string;
  turnstileToken: string;
}
export type RateSubmitResult = { ok: true; counter: number | null } | { ok: false; status: number; error: string };

/* The form waits on start, the context and the professor before it shows courses, so a hung request fails like any other. */
const RATE_WAIT_MS = 10000;

/* AbortSignal.timeout needs Safari 16, so the timer is set by hand. */
function rateSignal(): AbortSignal {
  const abort = new AbortController();
  setTimeout(() => abort.abort(), RATE_WAIT_MS);
  return abort.signal;
}

/* One retry, so a slow cold start of the backend doesn't end the form. */
async function rateGet(url: string, headers: Record<string, string>): Promise<Response> {
  try {
    return await fetch(url, { headers, signal: rateSignal() });
  } catch {
    return fetch(url, { headers, signal: rateSignal() });
  }
}

export const fetchRateProfessor = (slug: string) => fetchProfessorFull(slug, rateSignal());

/* The localStorage mirror of the device token goes in a header so it stays out of access logs. */
export async function startRating(deviceMirror: string | null): Promise<RateStart> {
  const res = await rateGet(`${API_BASE}/api/rate/start`, deviceMirror ? { "X-Rmh-Device": deviceMirror } : {});
  if (maintenanceGuard(res)) throw new Error("Site is under maintenance");
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

/* The device cookie doesn't reach a cross-site API, so the token also goes in the header. */
export async function fetchRateContext(slug: string, deviceToken: string): Promise<RateProfessorContext | null> {
  const res = await rateGet(`${API_BASE}/api/rate/professors/${encodeURIComponent(slug)}`, { "X-Rmh-Device": deviceToken });
  if (maintenanceGuard(res)) throw new Error("Site is under maintenance");
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

/* status 0 = network failure or the maintenance redirect. */
export async function submitRating(body: RateSubmission): Promise<RateSubmitResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/rate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, status: 0, error: "" };
  }
  if (maintenanceGuard(res)) return { ok: false, status: 0, error: "" };
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return { ok: false, status: res.status, error: typeof data.error === "string" ? data.error : "" };
  if ("slug" in body.professor) {
    _profPageCache.delete(body.professor.slug);
    _ratedProfPages.add(body.professor.slug);
  }
  return { ok: true, counter: typeof data.counter === "number" ? data.counter : null };
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