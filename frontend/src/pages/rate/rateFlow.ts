// Step logic and pure helpers for the /rate form. No React, no runtime imports from api.ts.
import type { ProfessorCourse, RateStart, RateSubmission, RatedCourse } from '../../api/api';

export type StepId = 'who' | 'newProfessor' | 'course' | 'otherCourse' | 'term' | 'otherTerm'
  | 'overall' | 'workload' | 'grade' | 'comment' | 'thanks';

export const QUESTION_COUNT = 7;

export interface RateProfessor { slug: string | null; name: string; department: string | null }
export interface RateCourse { code: string; name: string | null; isNew: boolean; terms: string[] }
export interface Answers {
  professor?: RateProfessor;
  course?: RateCourse;
  term?: string | null;
  rating?: number;
  hours?: string;
  grade?: string | null;
  comment: string;
  updating?: RatedCourse;
  // The fresh answers set aside while update mode shows the earlier ones.
  draft?: Pick<Answers, 'course' | 'term' | 'rating' | 'hours' | 'grade' | 'comment'>;
}

export const OVERALL: { value: number; label: string }[] = [
  { value: 5, label: 'Amazing' },
  { value: 4, label: 'Good' },
  { value: 3, label: 'Okay' },
  { value: 2, label: 'Poor' },
  { value: 1, label: 'Awful' },
];

// value is what the server accepts (ASCII hyphen); label is what the student sees.
export const HOURS: { value: string; label: string; aria: string }[] = [
  { value: '0-2', label: '0–2 hrs', aria: '0 to 2 hours' },
  { value: '3-4', label: '3–4 hrs', aria: '3 to 4 hours' },
  { value: '5-7', label: '5–7 hrs', aria: '5 to 7 hours' },
  { value: '8-10', label: '8–10 hrs', aria: '8 to 10 hours' },
  { value: '10+', label: '10+ hrs', aria: 'More than 10 hours' },
];

export const GRADES: string[] = ['A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C- or below'];

export const SEASONS: { value: string; label: string }[] = [
  { value: 'Fall', label: 'Fall' },
  { value: 'Spring', label: 'Spring' },
  { value: 'Summer 1', label: 'Summer 1' },
  { value: 'Summer 2', label: 'Summer 2' },
  { value: 'Summer', label: 'Full Summer' },
];

const MAIN_ORDER = ['who', 'course', 'term', 'overall', 'workload', 'grade', 'comment'] as const;
type MainStep = typeof MAIN_ORDER[number];

function mainOf(step: StepId): MainStep | null {
  switch (step) {
    case 'newProfessor': return 'who';
    case 'otherCourse': return 'course';
    case 'otherTerm': return 'term';
    case 'thanks': return null;
    default: return step;
  }
}

export function progressIndex(step: StepId): number {
  const main = mainOf(step);
  return main === null ? QUESTION_COUNT : MAIN_ORDER.indexOf(main);
}

function isAnswered(step: MainStep, a: Answers): boolean {
  switch (step) {
    case 'who': return a.professor !== undefined;
    case 'course': return a.course !== undefined;
    case 'term': return a.term !== undefined;
    case 'overall': return a.rating !== undefined;
    case 'workload': return a.hours !== undefined;
    case 'grade': return a.grade !== undefined;
    case 'comment': return false;
  }
}

// The screen to show for a question, after the two redirects.
function screenFor(step: MainStep, a: Answers): StepId {
  if (step === 'course' && a.professor?.slug === null) return 'otherCourse';
  if (step === 'term' && !a.course?.terms.length) return 'otherTerm';
  return step;
}

function firstUnansweredFrom(index: number, a: Answers): StepId {
  for (let i = index; i < MAIN_ORDER.length; i++) {
    if (!isAnswered(MAIN_ORDER[i], a)) return screenFor(MAIN_ORDER[i], a);
  }
  return 'thanks';
}

export function firstStep(a: Answers): StepId {
  if (a.updating && a.course) return screenFor('term', a);
  return firstUnansweredFrom(0, a);
}

export function nextStep(step: StepId, a: Answers): StepId {
  const main = mainOf(step);
  if (a.updating && main !== null && main !== 'comment') return screenFor(MAIN_ORDER[MAIN_ORDER.indexOf(main) + 1], a);
  // Scans from the start so an edit can't skip a question the student hasn't answered.
  return main === null || main === 'comment' ? 'thanks' : firstUnansweredFrom(0, a);
}

export function prevStep(step: StepId, a: Answers): StepId | null {
  const main = mainOf(step);
  if (main === null || step === 'who') return null;
  if (step === 'newProfessor') return 'who';
  if (step === 'otherCourse') return a.professor?.slug === null ? 'newProfessor' : 'course';
  if (step === 'otherTerm' && a.course?.terms.length) return 'term';
  return screenFor(MAIN_ORDER[MAIN_ORDER.indexOf(main) - 1], a);
}

function sameProfessor(x: RateProfessor | undefined, y: RateProfessor): boolean {
  return x !== undefined && x.slug === y.slug && (x.slug !== null || x.name === y.name);
}

// Leaving update mode brings back what the student had answered before entering it.
function leaveUpdate(a: Answers): Answers {
  const next: Answers = { ...a, rating: undefined, hours: undefined, grade: undefined, comment: '', ...a.draft };
  delete next.updating;
  delete next.draft;
  return next;
}

export function answer(a: Answers, change: Partial<Answers>): Answers {
  let next: Answers = { ...a, ...change };
  if (change.professor !== undefined && !sameProfessor(a.professor, change.professor)) {
    if (a.updating) next = leaveUpdate(next);
    if (!('course' in change)) delete next.course;
    if (!('term' in change)) delete next.term;
  }
  if (change.course !== undefined && a.course?.code !== change.course.code) {
    if (!('term' in change)) delete next.term;
  }
  return next;
}

// Picking a course: a rated one fills the student's earlier answers (update mode).
export function pickCourse(a: Answers, c: RateCourse, ratedCourses: RatedCourse[], now: Date): Answers {
  if (a.updating && a.course?.code === c.code) return a;
  const base = a.updating ? leaveUpdate(a) : a;
  const rated = ratedCourses.find((r) => r.code === c.code);
  if (!rated) return answer(base, { course: c });
  // The earlier term stays only where the term step can show it picked: as a tile, or on the different-term screen.
  const keep = rated.term === null
    || (c.terms.length > 0 ? inTermWindow(rated.term, now) : splitTerm(rated.term, now) !== null);
  const addTerm = keep && rated.term !== null && c.terms.length > 0 && !c.terms.includes(rated.term);
  const course = addTerm
    ? { ...c, terms: [...c.terms, rated.term as string].sort((x, y) => termOrder(y) - termOrder(x)) }
    : c;
  return answer(base, {
    course, term: keep ? rated.term : undefined, rating: rated.rating, hours: rated.hours,
    grade: rated.grade, comment: rated.comment, updating: rated,
    draft: { course: base.course, term: base.term, rating: base.rating, hours: base.hours, grade: base.grade, comment: base.comment },
  });
}

// Rated courses are the professor's listed ones, then any the term list no longer carries.
export function courseGroups(courses: RateCourse[], rated: RatedCourse[]): { fresh: RateCourse[]; rated: RateCourse[] } {
  const codes = new Set(rated.map((r) => r.code));
  const listed = new Set(courses.map((c) => c.code));
  const off = rated.filter((r) => !listed.has(r.code))
    .map((r): RateCourse => ({ code: r.code, name: r.name, isNew: r.pending, terms: [] }));
  return {
    fresh: courses.filter((c) => !codes.has(c.code)),
    rated: [...courses.filter((c) => codes.has(c.code)), ...off],
  };
}

export function splitTerm(label: string | null | undefined, now: Date): { season: string; year: number } | null {
  const m = label?.match(/^(.+) (\d{4})$/);
  if (!m || !SEASONS.some((x) => x.value === m[1]) || !termYears(now).includes(Number(m[2]))) return null;
  return { season: m[1], year: Number(m[2]) };
}

export function replacedLine(prior: RatedCourse): string {
  return prior.term === null
    ? 'Your new answers replaced your earlier ones.'
    : `Your new answers replaced the ones from ${displayTerm(prior.term)}.`;
}

// The backend's check (TERM_YEARS in backend/rating_checks.py) allows one more year each side, for a clock that differs from UTC.
const TERM_YEARS = 4;

export function termYears(now: Date): number[] {
  const y = now.getFullYear();
  return Array.from({ length: TERM_YEARS }, (_, i) => y - i);
}

// Banner's term code, as label_code in backend/teaching_history.py builds it, so terms order newest-first like the course list.
const SEASON_CODES: Record<string, [number, number]> = {
  Fall: [1, 10], Winter: [0, 25], Spring: [0, 30], 'Summer 1': [0, 40], Summer: [0, 50], 'Summer 2': [0, 60],
};

function termOrder(label: string): number {
  const m = label.match(/^(.+) (\d{4})$/);
  const code = m && SEASON_CODES[m[1]];
  return code ? (Number(m[2]) + code[0]) * 100 + code[1] : 0;
}

export function inTermWindow(label: string, now: Date): boolean {
  const year = Number(label.match(/(\d{4})$/)?.[1]);
  return termYears(now).includes(year);
}

export function toRateCourse(c: ProfessorCourse, now: Date): RateCourse {
  return { code: c.code, name: c.name, isNew: false, terms: c.terms.filter((t) => inTermWindow(t, now)) };
}

export function formatCode(code: string): string {
  return code.replace(/^([A-Za-z]+)(\d)/, '$1 $2');
}

export function displayTerm(label: string): string {
  return label.replace(/^Summer (\d{4})$/, 'Full Summer $1');
}

export function lastName(name: string): string {
  return name.trim().split(/\s+/).pop() ?? '';
}

export function contextTags(a: Answers): string[] {
  if (!a.professor) return [];
  if (!a.course) return [`Prof. ${a.professor.name}`];
  const parts = [lastName(a.professor.name), formatCode(a.course.code)];
  if (a.term !== undefined) parts.push(a.term === null ? 'Term not sure' : displayTerm(a.term));
  return parts;
}

// A rated course the professor's list no longer carries comes from the context, as on the course step.
export function prefillCourse(courses: ProfessorCourse[], rated: RatedCourse[], code: string | null, now: Date): RateCourse | undefined {
  if (!code) return undefined;
  const c = courses.find((x) => x.code === code);
  return c ? toRateCourse(c, now) : courseGroups([], rated).rated.find((x) => x.code === code);
}

export function buildSubmission(a: Answers, start: RateStart, turnstileToken: string, honeypot: string): RateSubmission {
  // undefined is unanswered; null is "Not sure" or "Prefer not to say".
  if (!a.professor || !a.course || a.term === undefined || a.rating === undefined || a.hours === undefined || a.grade === undefined) {
    throw new Error('Incomplete rating');
  }
  return {
    professor: a.professor.slug !== null
      ? { slug: a.professor.slug }
      : { name: a.professor.name, department: a.professor.department },
    course: a.course.isNew ? { code: a.course.code, name: a.course.name ?? '' } : { code: a.course.code },
    term: a.term ?? null,
    rating: a.rating,
    hours: a.hours,
    grade: a.grade ?? null,
    comment: a.comment,
    opened: start.opened,
    deviceToken: start.deviceToken,
    website: honeypot,
    turnstileToken,
  };
}
