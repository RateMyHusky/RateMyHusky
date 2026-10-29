// Runnable self-check for rateFlow (no unit-test framework is installed).
// Run: cd frontend && npx tsx src/pages/rate/rateFlow.selftest.ts
// Prints PASS/FAIL per check and exits non-zero on any failure.
import { argv } from 'node:process';
import { fileURLToPath } from 'node:url';
import {
  answer, buildSubmission, contextTags, courseGroups, displayTerm, firstStep, formatCode,
  inTermWindow, lastName, nextStep, ownMatches, pickCourse, prefillCourse, prevStep, progressIndex, replacedLine,
  splitTerm, termYears, toRateCourse,
  SEASONS,
  type Answers, type RateCourse, type RateProfessor,
} from './rateFlow';
import type { ProfessorCourse, RateStart, RatedCourse } from '../../api/api';

function selftest(): number {
  const fails: string[] = [];
  const check = (label: string, cond: boolean) => {
    if (!cond) fails.push(label);
    console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  };
  const same = (x: unknown, y: unknown) => JSON.stringify(x) === JSON.stringify(y);

  const alex: RateProfessor = { slug: 'alex-rivera', name: 'Alex Rivera', department: 'CS' };
  const newProf: RateProfessor = { slug: null, name: 'Sam Newhire', department: null };
  const cs2500: RateCourse = { code: 'CS2500', name: 'Fundamentals of CS 1', isNew: false, terms: ['Summer 1 2025', 'Fall 2024'] };
  const noShortcuts: RateCourse = { code: 'CS3000', name: 'Algorithms', isNew: false, terms: [] };
  const newCourse: RateCourse = { code: 'CS9999', name: 'Brand New', isNew: true, terms: [] };

  // Linear first pass
  let a: Answers = { comment: '' };
  check('firstStep on empty answers is who', firstStep(a) === 'who');
  let s = nextStep('who', (a = answer(a, { professor: alex })));
  check('who -> course', s === 'course');
  s = nextStep(s, (a = answer(a, { course: cs2500 })));
  check('course -> term', s === 'term');
  s = nextStep(s, (a = answer(a, { term: 'Summer 1 2025' })));
  check('term -> overall', s === 'overall');
  s = nextStep(s, (a = answer(a, { rating: 5 })));
  check('overall -> difficulty', s === 'difficulty');
  s = nextStep(s, (a = answer(a, { difficulty: 3 })));
  check('difficulty -> workload', s === 'workload');
  s = nextStep(s, (a = answer(a, { hours: '5-7' })));
  check('workload -> grade', s === 'grade');
  s = nextStep(s, (a = answer(a, { grade: null })));
  check('grade -> comment', s === 'comment');
  const rePicked = answer(a, { professor: { slug: 'sam-lee', name: 'Sam Lee', department: null } });
  check('who -> course after re-picking professor', nextStep('who', rePicked) === 'course');
  check('re-pick professor, edit overall -> course', nextStep('overall', answer(rePicked, { rating: 3 })) === 'course');
  check('edit course, edit grade -> term', nextStep('grade', answer(answer(a, { course: { ...cs2500, code: 'CS3500' } }), { grade: 'A' })) === 'term');
  check('comment -> thanks', nextStep('comment', a) === 'thanks');

  // Edits return to comment / next unanswered
  check('edit grade after comment reached returns to comment', nextStep('grade', answer(a, { grade: 'A' })) === 'comment');
  const editedCourse = answer(a, { course: noShortcuts });
  check('edit course clears term', editedCourse.term === undefined && editedCourse.course?.code === 'CS3000');
  check('edit course without shortcuts goes to otherTerm', nextStep('course', editedCourse) === 'otherTerm');
  const editedCourse2 = answer(a, { course: { ...cs2500, code: 'CS2510' } });
  check('edit course with shortcuts goes to term', nextStep('course', editedCourse2) === 'term');
  // The difficulty question names the course, so another course asks it again.
  check('edit course clears difficulty', editedCourse2.difficulty === undefined);
  check('edit course: term -> difficulty', nextStep('term', answer(editedCourse2, { term: 'Fall 2025' })) === 'difficulty');
  const editedProf = answer(a, { professor: { ...alex, slug: 'other', name: 'Other Prof' } });
  check('edit professor clears course and term', editedProf.course === undefined && editedProf.term === undefined);
  check('edit professor keeps later answers', editedProf.rating === 5 && editedProf.hours === '5-7');
  const reselect = answer(a, { professor: { ...alex }, course: { ...cs2500 } });
  check('re-selecting same professor/course clears nothing', reselect.course?.code === 'CS2500' && reselect.term === 'Summer 1 2025');
  check('null term (Not sure) counts as answered', nextStep('course', { comment: '', professor: alex, course: cs2500, term: null }) === 'overall');

  // New professor path
  let n: Answers = answer({ comment: '' }, { professor: newProf });
  check('new professor: who -> otherCourse (skips course list)', nextStep('who', n) === 'otherCourse');
  check('new professor: newProfessor -> otherCourse', nextStep('newProfessor', n) === 'otherCourse');
  n = answer(n, { course: newCourse });
  check('otherCourse -> otherTerm for new course (no shortcuts)', nextStep('otherCourse', n) === 'otherTerm');
  check('otherTerm -> overall', nextStep('otherTerm', answer(n, { term: 'Fall 2025' })) === 'overall');
  check('prevStep otherCourse (new professor) -> newProfessor', prevStep('otherCourse', n) === 'newProfessor');
  check('prevStep otherCourse (existing professor) -> course', prevStep('otherCourse', a) === 'course');
  check('prevStep newProfessor -> who', prevStep('newProfessor', n) === 'who');

  // No-shortcuts term path
  const ns = answer(answer({ comment: '' }, { professor: alex }), { course: noShortcuts });
  check('no shortcuts: course -> otherTerm', nextStep('course', ns) === 'otherTerm');
  check('prevStep otherTerm (no shortcuts) -> course', prevStep('otherTerm', ns) === 'course');
  check('prevStep otherTerm (new professor) -> otherCourse', prevStep('otherTerm', n) === 'otherCourse');
  check('prevStep term -> course', prevStep('term', a) === 'course');
  check('prevStep overall -> term when shortcuts', prevStep('overall', a) === 'term');
  check('prevStep overall -> otherTerm when no shortcuts', prevStep('overall', ns) === 'otherTerm');
  check('prevStep who is null', prevStep('who', a) === null);
  check('prevStep comment -> grade', prevStep('comment', a) === 'grade');
  check('prevStep workload -> difficulty', prevStep('workload', a) === 'difficulty');

  // firstStep with prefill
  check('firstStep with professor prefilled is course', firstStep({ comment: '', professor: alex }) === 'course');
  check('firstStep with professor and course prefilled is term', firstStep({ comment: '', professor: alex, course: cs2500 }) === 'term');
  check('firstStep with new professor prefilled is otherCourse', firstStep({ comment: '', professor: newProf }) === 'otherCourse');

  // prefillCourse
  const june26 = new Date(2026, 5, 1);
  const courses = [
    { code: 'CS2500', name: 'Fundamentals of CS 1', terms: ['Fall 2024'] },
  ] as ProfessorCourse[];
  check('prefillCourse unknown code is undefined', prefillCourse(courses, [], 'ZZ1111', june26) === undefined);
  check('prefillCourse null code is undefined', prefillCourse(courses, [], null, june26) === undefined);
  const pf = prefillCourse(courses, [], 'CS2500', june26);
  check('prefillCourse known code', pf?.code === 'CS2500' && pf.isNew === false && same(pf.terms, ['Fall 2024']));
  const ratedOff: RatedCourse = { code: 'CS4973', name: 'Topics in HCI', pending: false, term: null, rating: 5, difficulty: null, hours: '8-10', grade: null, comment: '' };
  const pfOff = prefillCourse(courses, [ratedOff], 'CS4973', june26);
  check('prefillCourse finds a rated course the list no longer carries', same(pfOff, { code: 'CS4973', name: 'Topics in HCI', isNew: false, terms: [] }));

  // contextTags
  check('contextTags empty answers', same(contextTags({ comment: '' }), []));
  check('contextTags professor only', same(contextTags({ comment: '', professor: alex }), ['Prof. Alex Rivera']));
  check('contextTags professor + course', same(contextTags({ comment: '', professor: alex, course: cs2500 }), ['Rivera', 'CS 2500']));
  check('contextTags full', same(contextTags(a), ['Rivera', 'CS 2500', 'Summer 1 2025']));
  check('contextTags Not sure term', same(contextTags(answer(a, { term: null })), ['Rivera', 'CS 2500', 'Term not sure']));
  check('contextTags full summer', same(contextTags(answer(a, { term: 'Summer 2025' })), ['Rivera', 'CS 2500', 'Full Summer 2025']));

  // Terms
  check('displayTerm Summer 2025', displayTerm('Summer 2025') === 'Full Summer 2025');
  check('displayTerm Winter 2026', displayTerm('Winter 2026') === 'Winter 2026');
  check('displayTerm Summer 1 2025', displayTerm('Summer 1 2025') === 'Summer 1 2025');
  const full = SEASONS.find((x) => x.label === 'Full Summer');
  check('Full Summer + 2025 answers Summer 2025', full !== undefined && answer({ comment: '' }, { term: `${full.value} 2025` }).term === 'Summer 2025');
  check('SEASONS has five options', SEASONS.length === 5);
  check('termYears is four years', same(termYears(june26), [2026, 2025, 2024, 2023]));
  check('inTermWindow edges', inTermWindow('Fall 2023', june26) && inTermWindow('Winter 2026', june26)
    && !inTermWindow('Summer 2 2022', june26) && !inTermWindow('Spring 2027', june26));
  const old = toRateCourse({ code: 'CS3000', name: 'Algorithms', terms: ['Fall 2026', 'Spring 2027', 'Fall 2021'] } as ProfessorCourse, june26);
  check('toRateCourse keeps only window terms', same(old.terms, ['Fall 2026']) && old.isNew === false);
  const allOld = toRateCourse({ code: 'CS3000', name: 'Algorithms', terms: ['Fall 2021'] } as ProfessorCourse, june26);
  check('course with only old terms opens otherTerm', firstStep({ comment: '', professor: alex, course: allOld }) === 'otherTerm');
  const futureOnly = toRateCourse({ code: 'CS3000', name: 'Algorithms', terms: ['Spring 2027'] } as ProfessorCourse, june26);
  check('course with only a future term opens otherTerm', firstStep({ comment: '', professor: alex, course: futureOnly }) === 'otherTerm');

  // Misc formatting
  check('formatCode CS4973', formatCode('CS4973') === 'CS 4973');
  check('lastName', lastName('Lucia Nunez') === 'Nunez');
  check('progressIndex', progressIndex('newProfessor') === 0 && progressIndex('who') === 0 && progressIndex('difficulty') === 4 && progressIndex('comment') === 7 && progressIndex('thanks') === 8);

  // buildSubmission
  const start: RateStart = { opened: 'tok', deviceToken: 'dev', counter: 3 };
  const sub = buildSubmission({ comment: 'ok', professor: newProf, course: newCourse, term: null, rating: 4, difficulty: 2, hours: '3-4', grade: null }, start, 'ts', 'hp');
  check('buildSubmission new professor and course',
    same(sub.professor, { name: 'Sam Newhire', department: null }) && same(sub.course, { code: 'CS9999', name: 'Brand New' }));
  check('buildSubmission passthrough',
    sub.term === null && sub.grade === null && sub.rating === 4 && sub.difficulty === 2 && sub.hours === '3-4' && sub.comment === 'ok' &&
    sub.opened === 'tok' && sub.deviceToken === 'dev' && sub.website === 'hp' && sub.turnstileToken === 'ts');
  const sub2 = buildSubmission({ ...a, comment: 'x' }, start, 't', '');
  check('buildSubmission existing professor and course', same(sub2.professor, { slug: 'alex-rivera' }) && same(sub2.course, { code: 'CS2500' }));
  const throws = (x: Answers) => { try { buildSubmission(x, start, 't', ''); return false; } catch { return true; } };
  const noTerm: Answers = { ...a, term: undefined };
  const noGradeYet: Answers = { ...a, grade: undefined };
  const noDifficulty: Answers = { ...a, difficulty: undefined };
  check('buildSubmission throws on an unanswered difficulty', throws(noDifficulty) && firstStep(noDifficulty) === 'difficulty');
  check('buildSubmission throws on an unanswered term', throws(noTerm) && firstStep(noTerm) === 'term');
  check('buildSubmission throws on an unanswered grade', throws(noGradeYet) && firstStep(noGradeYet) === 'grade');

  // Update mode
  const now = new Date(2026, 9, 23);
  const prior: RatedCourse = { code: 'CS3500', name: 'Object-Oriented Design', pending: false, term: 'Fall 2025', rating: 4, difficulty: 4, hours: '5-7', grade: 'A-', comment: 'Projects take time.' };
  const priorB: RatedCourse = { code: 'CS4973', name: 'Topics in HCI', pending: false, term: null, rating: 5, difficulty: 2, hours: '8-10', grade: null, comment: 'Best course.' };
  const cs3500: RateCourse = { code: 'CS3500', name: 'Object-Oriented Design', isNew: false, terms: ['Fall 2025', 'Spring 2025'] };
  const cs4973: RateCourse = { code: 'CS4973', name: 'Topics in HCI', isNew: false, terms: ['Spring 2025'] };
  const u = pickCourse({ comment: '', professor: alex }, cs3500, [prior], now);
  check('update: pick fills the earlier answers', u.term === 'Fall 2025' && u.rating === 4 && u.difficulty === 4 && u.hours === '5-7'
    && u.grade === 'A-' && u.comment === 'Projects take time.' && u.updating?.code === 'CS3500');
  check('update: every step follows in order', nextStep('course', u) === 'term' && nextStep('term', u) === 'overall'
    && nextStep('overall', u) === 'difficulty' && nextStep('difficulty', u) === 'workload' && nextStep('workload', u) === 'grade'
    && nextStep('grade', u) === 'comment' && nextStep('comment', u) === 'thanks');
  check('update: otherTerm -> overall, firstStep is term, edit overall -> workload',
    nextStep('otherTerm', u) === 'overall' && firstStep(u) === 'term' && nextStep('overall', answer(u, { rating: 2 })) === 'difficulty');
  const beforeDifficulty = pickCourse({ comment: '', professor: alex }, cs3500, [{ ...prior, difficulty: null }], now);
  check('update: a rating from before the difficulty question asks it',
    beforeDifficulty.difficulty === undefined && throws(beforeDifficulty)
    && throws(answer(beforeDifficulty, { comment: 'x' })) && !throws(answer(beforeDifficulty, { difficulty: 5 })));
  check('update: re-picking the same course keeps edits', pickCourse(answer(u, { rating: 2 }), cs3500, [prior], now).rating === 2);
  const ub = pickCourse(u, cs4973, [prior, priorB], now);
  check('update: rated A -> rated B fills B only', ub.term === null && ub.rating === 5 && ub.grade === null
    && ub.comment === 'Best course.' && ub.updating?.code === 'CS4973');
  const toFresh = pickCourse(answer(u, { rating: 2 }), cs2500, [prior], now);
  check('update: rated -> unrated clears everything', toFresh.updating === undefined && toFresh.term === undefined
    && toFresh.rating === undefined && toFresh.difficulty === undefined && toFresh.hours === undefined && toFresh.grade === undefined
    && toFresh.comment === '' && toFresh.course?.code === 'CS2500' && nextStep('course', toFresh) === 'term');
  const plain = pickCourse(a, { ...cs2500, code: 'CS2510' }, [], now);
  check('unrated pick outside update mode behaves like answer', plain.rating === 5 && plain.term === undefined);
  const odd = pickCourse({ comment: '', professor: alex }, cs3500, [{ ...prior, term: 'Summer 1 2024' }], now);
  check('earlier term in the window but unlisted is added', odd.course?.terms.includes('Summer 1 2024') === true && odd.term === 'Summer 1 2024');
  const newer = pickCourse({ comment: '', professor: alex }, cs3500, [{ ...prior, term: 'Spring 2026' }], now);
  check('an added earlier term keeps the list newest-first', same(newer.course?.terms, ['Spring 2026', 'Fall 2025', 'Spring 2025']));
  const summers = pickCourse({ comment: '', professor: alex }, { ...cs3500, terms: ['Fall 2025', 'Summer 2 2025', 'Spring 2025'] }, [{ ...prior, term: 'Summer 1 2025' }], now);
  check('an added summer session orders by its session', same(summers.course?.terms, ['Fall 2025', 'Summer 2 2025', 'Summer 1 2025', 'Spring 2025']));
  const winterOff = pickCourse({ comment: '', professor: alex }, { ...cs3500, terms: [] }, [{ ...prior, term: 'Winter 2026' }], now);
  check('an earlier term the different-term screen cannot show is asked again', winterOff.term === undefined && firstStep(winterOff) === 'otherTerm');
  const winterListed = pickCourse({ comment: '', professor: alex }, cs3500, [{ ...prior, term: 'Winter 2026' }], now);
  check('an earlier Winter term on a listed course stays as a tile', winterListed.term === 'Winter 2026'
    && same(winterListed.course?.terms, ['Winter 2026', 'Fall 2025', 'Spring 2025']));
  const stale = pickCourse({ comment: '', professor: alex }, cs3500, [{ ...prior, term: 'Fall 2021' }], now);
  check('earlier term older than the window is not selected', stale.term === undefined
    && same(stale.course?.terms, cs3500.terms) && nextStep('course', stale) === 'term');
  const off = pickCourse({ comment: '', professor: alex }, { ...cs3500, terms: [] }, [prior], now);
  check('off-list course keeps terms empty and opens otherTerm', off.course?.terms.length === 0 && nextStep('course', off) === 'otherTerm');
  const swapped = answer(u, { professor: { slug: 'sam-lee', name: 'Sam Lee', department: null } });
  check('professor change leaves update mode', swapped.updating === undefined && swapped.course === undefined
    && swapped.term === undefined && swapped.rating === undefined && swapped.hours === undefined
    && swapped.grade === undefined && swapped.comment === '');
  const drafted: Answers = { comment: 'Half-written draft.', professor: alex, course: cs2500, term: 'Fall 2025', rating: 3, difficulty: 1, hours: '3-4', grade: 'B' };
  const misTap = pickCourse(drafted, cs3500, [prior], now);
  check('update: entering keeps the fresh draft aside', misTap.rating === 4 && misTap.comment === 'Projects take time.');
  const backToDraft = pickCourse(pickCourse(misTap, cs4973, [prior, priorB], now), cs2500, [prior, priorB], now);
  check('update: leaving restores the fresh draft', backToDraft.updating === undefined && backToDraft.rating === 3
    && backToDraft.difficulty === 1
    && backToDraft.hours === '3-4' && backToDraft.grade === 'B' && backToDraft.comment === 'Half-written draft.'
    && backToDraft.term === 'Fall 2025' && backToDraft.course?.code === 'CS2500');
  const elsewhere = pickCourse(misTap, cs4973, [prior], now);
  check('update: leaving for another course drops the draft term', elsewhere.term === undefined && elsewhere.rating === 3);
  const swappedDraft = answer(misTap, { professor: { slug: 'sam-lee', name: 'Sam Lee', department: null } });
  check('update: professor change restores the fresh draft', swappedDraft.updating === undefined
    && swappedDraft.rating === 3 && swappedDraft.comment === 'Half-written draft.' && swappedDraft.course === undefined);
  const groups = courseGroups([cs2500, cs3500], [prior, priorB]);
  check('courseGroups splits fresh and rated', same(groups.fresh.map((c) => c.code), ['CS2500'])
    && same(groups.rated.map((c) => c.code), ['CS3500', 'CS4973'])
    && same(groups.rated[0].terms, cs3500.terms) && same(groups.rated[1].terms, []) && groups.rated[1].name === 'Topics in HCI');
  const many: RateCourse[] = Array.from({ length: 9 }, (_, i) => ({ code: `CS${3600 + i}`, name: null, isNew: false, terms: [] }));
  const capped = courseGroups([...many, cs3500], [prior, priorB]);
  check('courseGroups shows the six most recent fresh courses', same(capped.fresh.map((c) => c.code), many.slice(0, 6).map((c) => c.code))
    && capped.more && same(capped.rated.map((c) => c.code), ['CS3500', 'CS4973']));
  check('courseGroups keeps a picked hidden course', same(courseGroups(many, [], 'CS3608').fresh.map((c) => c.code).slice(-1), ['CS3608']));
  check('courseGroups has no more at six', !courseGroups(many.slice(0, 6), []).more && !groups.more);
  check('ownMatches finds by code or name, any case', same(ownMatches([cs2500, cs3500, noShortcuts], 'cs3500').map((c) => c.code), ['CS3500'])
    && same(ownMatches([cs2500, cs3500, noShortcuts], 'algo').map((c) => c.code), ['CS3000'])
    && ownMatches([cs2500], 'c').length === 0);
  const pendingPrior: RatedCourse = { ...prior, code: 'CS4999', name: 'Applied ML', pending: true };
  const [pendingTile] = courseGroups([], [pendingPrior]).rated;
  const subPending = buildSubmission(pickCourse({ comment: '', professor: alex }, pendingTile, [pendingPrior], now), start, 't', '');
  check('a rated course awaiting review resends as a new course', same(subPending.course, { code: 'CS4999', name: 'Applied ML' }));
  check('splitTerm', same(splitTerm('Summer 1 2025', now), { season: 'Summer 1', year: 2025 })
    && same(splitTerm('Summer 2025', now), { season: 'Summer', year: 2025 })
    && splitTerm('Winter 2026', now) === null && splitTerm('Fall 2021', now) === null && splitTerm(null, now) === null);
  check('replacedLine', replacedLine(prior) === 'Your new answers replaced the ones from Fall 2025.'
    && replacedLine({ ...prior, term: 'Summer 2025' }).endsWith('from Full Summer 2025.')
    && replacedLine({ ...prior, term: null }) === 'Your new answers replaced your earlier ones.');
  const subU = buildSubmission(u, start, 't', '');
  check('buildSubmission ignores updating', !('updating' in subU) && subU.comment === 'Projects take time.');

  console.log(fails.length ? `${fails.length} FAIL(s): ` + fails.join(', ') : 'ALL PASS');
  return fails.length ? 1 : 0;
}

if (argv[1] && fileURLToPath(import.meta.url) === argv[1]) {
  process.exit(selftest());
}
