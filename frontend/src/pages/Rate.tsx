import { Fragment, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { fetchRateContext, fetchRateProfessor, startRating, submitRating } from '../api/api';
import type { ProfessorPage, RatedCourse, RateStart, RateSubmission } from '../api/api';
import { useTurnstile } from './rate/useTurnstile';
import { WhoStep, NewProfessorStep } from './rate/WhoStep';
import { CourseStep, OtherCourseStep } from './rate/CourseStep';
import { TermStep, OtherTermStep } from './rate/TermStep';
import { CommentStep } from './rate/CommentStep';
import { ThanksStep } from './rate/ThanksStep';
import { Celebration } from './rate/Celebration';
import { ChoiceGroup, StepFoot } from './rate/ChoiceGroup';
import { ProgressBar } from './rate/ProgressBar';
import { useMediaQuery } from './rate/useMediaQuery';
import type { ChoiceOption } from './rate/ChoiceGroup';
import {
  DIFFICULTY, GRADES, HOURS, OVERALL, answer, buildSubmission, contextTags, courseGroups, firstStep, formatCode,
  lastName, nextStep, pickCourse, prefillCourse, prevStep, progressIndex, toRateCourse,
} from './rate/rateFlow';
import type { Answers, RateCourse, RateProfessor, StepId } from './rate/rateFlow';
import './Rate.css';

const PICK_DELAY_MS = 200;

const DEVICE_KEY = 'rmh_device';

function readMirror(): string | null {
  try {
    return localStorage.getItem(DEVICE_KEY);
  } catch {
    return null;
  }
}

function writeMirror(token: string) {
  try {
    localStorage.setItem(DEVICE_KEY, token);
  } catch {
    /* the cookie still identifies the device */
  }
}

const FAILURE_MESSAGES: Record<number, string> = {
  400: "Something in this rating didn't go through. Check your answers and try again.",
  403: "We couldn't check you're human. Try again.",
  422: "This comment can't be posted. Edit it or skip it.",
  429: 'Too many ratings from this device for now. Try again later.',
  503: 'Ratings are paused right now. Try again later.',
};
const TOKEN_WAIT_MS = 15000;
const NETWORK_MESSAGE = "Couldn't send. Check your connection and try again.";

const gradeAria = (g: string) => `Grade ${g.replace('+', ' plus').replace('-', ' minus')}`;

const toRateCourses = (page: ProfessorPage): RateCourse[] =>
  page.courses.map((c) => toRateCourse(c, new Date()));

export default function Rate() {
  const [params] = useSearchParams();
  const [ready, setReady] = useState(false);
  const [answers, setAnswers] = useState<Answers>({ comment: '' });
  const [step, setStep] = useState<StepId>('who');
  const [start, setStart] = useState<RateStart | null>(null);
  const [startFailed, setStartFailed] = useState(false);
  // recent: the list is Banner's newest-first order; without Banner history it is most-rated first.
  const [loaded, setLoaded] = useState<{ slug: string; list: RateCourse[]; recent: boolean } | null>(null);
  const [context, setContext] = useState<{ slug: string; rated: RatedCourse[] } | null>(null);
  const [typedName, setTypedName] = useState('');
  const [counter, setCounter] = useState<number | null>(null);
  const [submitError, setSubmitError] = useState('');
  // until: when the wait gives up, fixed at submit so a re-run of the timer effect can't extend it.
  const [pending, setPending] = useState<{ skip: boolean; honeypot: string; until: number } | null>(null);
  const [sending, setSending] = useState(false);
  const [contextReload, setContextReload] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const visitRef = useRef(0);
  const pickTimer = useRef<number | undefined>(undefined);
  // The start the prefill already fetched the context with, so the context effect doesn't fetch it again.
  const prefetchedFor = useRef<RateStart | null>(null);
  const reduced = useMediaQuery('(prefers-reduced-motion: reduce)');
  const { containerRef, token, failed, interactive, reset } = useTurnstile();
  // The checkpoint holds the form back until the first token; later re-checks happen under the form.
  // Starts cleared when the token is already there (no site key), so the checkpoint never flashes.
  const [cleared, setCleared] = useState(() => !!token);

  const slug = answers.professor?.slug ?? null;
  // null while the professor's courses load; a new professor has none to load.
  const courses = slug === null ? [] : loaded?.slug === slug ? loaded.list : null;
  // null until the context call settles; a failed call or a new professor leaves every course not rated.
  const rated: RatedCourse[] | null = slug === null || startFailed ? [] : context?.slug === slug ? context.rated : null;
  const coursesLoading = courses === null || rated === null;

  // Only the latest visit's start lands, so a slow earlier one can't overwrite it.
  const beginVisit = (): Promise<RateStart | null> => {
    const visit = ++visitRef.current;
    setStartFailed(false);
    return startRating(readMirror())
      .then((s) => {
        if (visitRef.current !== visit) return null;
        writeMirror(s.deviceToken);
        setStart(s);
        return s;
      })
      .catch(() => {
        if (visitRef.current === visit) setStartFailed(true);
        return null;
      });
  };

  // Start the visit, then resolve any ?professor / ?course prefill.
  useEffect(() => {
    let cancelled = false;
    const visit = beginVisit();

    (async () => {
      const profSlug = params.get('professor');
      let initial: Answers = { comment: '' };
      let prefetched: RatedCourse[] | null = null;
      let s: RateStart | null = null;
      if (profSlug) {
        const res = await fetchRateProfessor(profSlug);
        if (res.ok) {
          const { identity } = res.data;
          const professor: RateProfessor = { slug: identity.slug, name: identity.name, department: identity.department };
          const code = (params.get('course') ?? '').replace(/\s+/g, '').toUpperCase() || null;
          initial = answer(initial, { professor });
          if (code) {
            // A prefilled rated course opens in update mode, so wait for the context before the first screen.
            s = await visit;
            // A failed call stays null, so the context effect fetches it again rather than keep an empty list.
            if (s) prefetched = await fetchRateContext(identity.slug, s.deviceToken).then((c) => c?.ratedCourses ?? [], () => null);
            const course = prefillCourse(res.data.courses, prefetched ?? [], code, new Date());
            if (course) initial = pickCourse(initial, course, prefetched ?? [], new Date());
          }
        }
      }
      if (cancelled) return;
      // Kept, and not fetched again, so the course step can't disagree with the update mode the first screen chose.
      if (prefetched && initial.professor?.slug) {
        prefetchedFor.current = s;
        setContext({ slug: initial.professor.slug, rated: prefetched });
      }
      setAnswers(initial);
      setStep(firstStep(initial));
      setReady(true);
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the prefill is read once, on mount
  }, []);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    fetchRateProfessor(slug)
      .then((res) => { if (!cancelled) setLoaded({ slug, list: res.ok ? toRateCourses(res.data) : [], recent: res.ok && res.data.lastTaught !== null }); })
      .catch(() => { if (!cancelled) setLoaded({ slug, list: [], recent: false }); });
    return () => { cancelled = true; };
  }, [slug]);

  // The context call needs the device token from startRating, so it waits for start.
  useEffect(() => {
    if (!start || !slug) return;
    if (prefetchedFor.current === start) {
      prefetchedFor.current = null;
      return;
    }
    let cancelled = false;
    fetchRateContext(slug, start.deviceToken)
      .then((c) => { if (!cancelled) setContext({ slug, rated: c?.ratedCourses ?? [] }); })
      // No "Already rated" group, so every course shows as not rated.
      .catch(() => { if (!cancelled) setContext({ slug, rated: [] }); });
    return () => { cancelled = true; };
  }, [start, slug, contextReload]);

  const send = (skip: boolean, honeypot: string, turnstileToken: string) => {
    if (!start) return;
    let body: RateSubmission;
    try {
      body = buildSubmission({ ...answers, comment: skip ? '' : answers.comment }, start, turnstileToken, honeypot);
    } catch {
      setStep(firstStep(answers));
      return;
    }
    setSending(true);
    submitRating(body).then((res) => {
      setSending(false);
      if (res.ok) {
        if (skip) setAnswers((a) => ({ ...a, comment: '' }));
        setCounter(res.counter);
        reset();
        setStep('thanks');
        setContextReload((n) => n + 1);
        return;
      }
      // Turnstile tokens are single-use, so every retry needs a fresh one.
      reset();
      setSubmitError(FAILURE_MESSAGES[res.status] ?? (res.error || NETWORK_MESSAGE));
    });
  };

  const submit = (skip: boolean, honeypot: string) => {
    setSubmitError('');
    if (token && start) send(skip, honeypot, token);
    else {
      // An earlier challenge error would end this wait at once, so run a fresh challenge.
      if (failed) reset();
      setPending({ skip, honeypot, until: Date.now() + TOKEN_WAIT_MS });
      if (!start) beginVisit();
    }
  };

  // A submit that arrived before the Turnstile token or the visit start waits here.
  useEffect(() => {
    if (!pending || !token || !start) return;
    setPending(null);
    send(pending.skip, pending.honeypot, token);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fires once when the token arrives
  }, [pending, token, start]);

  // Bound the wait for the token or the visit start so a blocked challenge can't leave the step stuck.
  useEffect(() => {
    if (!pending) return;
    const giveUp = () => {
      setPending(null);
      setSubmitError(start ? FAILURE_MESSAGES[403] : NETWORK_MESSAGE);
      reset();
    };
    if (failed || startFailed) {
      giveUp();
      return;
    }
    const timer = setTimeout(giveUp, pending.until - Date.now());
    return () => clearTimeout(timer);
  }, [pending, failed, startFailed, reset, start]);

  const rateAnother = () => {
    window.clearTimeout(pickTimer.current);
    setAnswers({ comment: '' });
    setStep('who');
    setStart(null);
    setContext(null);
    setCounter(null);
    setSubmitError('');
    setTypedName('');
    setContextReload((n) => n + 1);
    beginVisit();
  };

  useEffect(() => () => window.clearTimeout(pickTimer.current), []);

  useEffect(() => { if (token) setCleared(true); }, [token]);

  // The checkpoint stands alone, like Cloudflare's own page, so the navbar waits with the form.
  useEffect(() => {
    document.body.classList.toggle('rate-checking', !cleared);
    return () => document.body.classList.remove('rate-checking');
  }, [cleared]);

  // /rate's URL never changes, so ScrollToTop never fires; every step opens at the top, as an instant jump.
  useLayoutEffect(() => { window.scrollTo(0, 0); }, [step]);

  useEffect(() => {
    if (ready) panelRef.current?.querySelector<HTMLElement>('h1')?.focus({ preventScroll: true });
  }, [step, ready, coursesLoading, cleared]);

  const go = (next: Answers, from: StepId) => {
    window.clearTimeout(pickTimer.current);
    setAnswers(next);
    setStep(nextStep(from, next));
  };

  // Shows the pick for a beat before the next step opens; a later tap replaces a pending one.
  const choose = (next: Answers, from: StepId) => {
    setAnswers(next);
    window.clearTimeout(pickTimer.current);
    if (reduced) setStep(nextStep(from, next));
    else pickTimer.current = window.setTimeout(() => setStep(nextStep(from, next)), PICK_DELAY_MS);
  };

  // A direct move to a sub-screen also cancels a pick still waiting to advance.
  const open = (next: StepId) => {
    window.clearTimeout(pickTimer.current);
    setStep(next);
  };

  const pickProfessor = (p: RateProfessor, from: StepId) => {
    go(answer(answers, { professor: p }), from);
  };

  const back = () => {
    window.clearTimeout(pickTimer.current);
    const prev = prevStep(step, answers);
    if (prev) setStep(prev);
  };

  // In update mode a step with an earlier answer can be passed over without tapping a tile.
  const continueButton = (answered: boolean) =>
    answers.updating && answered ? (
      <button type="button" className="rate-btn" onClick={() => open(nextStep(step, answers))}>Continue</button>
    ) : undefined;

  const renderStep = () => {
    switch (step) {
      case 'who':
        return (
          <>
            <WhoStep
              onPick={(p) => pickProfessor(p, 'who')}
              onAddNew={(name) => { setTypedName(name); open('newProfessor'); }}
            />
            <StepFoot />
          </>
        );
      case 'newProfessor':
        return <NewProfessorStep initialName={typedName} onContinue={(p) => pickProfessor(p, 'newProfessor')} onBack={back} />;
      case 'course': {
        if (!answers.professor) return null;
        if (courses === null || rated === null) {
          return (
            <>
              <h1 className="rate-q" tabIndex={-1}>Which course?</h1>
              <p className="rate-hint" role="status">Loading courses…</p>
              <StepFoot onBack={back} />
            </>
          );
        }
        const groups = courseGroups(courses, rated, answers.course?.code);
        return (
          <>
            <CourseStep
              professor={answers.professor}
              fresh={groups.fresh}
              rated={groups.rated}
              more={groups.more}
              recent={loaded?.recent ?? false}
              selected={answers.course?.code}
              onPick={(c) => choose(pickCourse(answers, c, rated, new Date()), 'course')}
              onOther={() => open('otherCourse')}
            />
            <StepFoot onBack={back} />
          </>
        );
      }
      case 'otherCourse':
        return (
          <OtherCourseStep
            own={courses ?? []}
            rated={(rated ?? []).map((r) => r.code)}
            slug={answers.professor?.slug ?? null}
            // A hit on the professor's list takes the listed course, so its terms show.
            onPick={(c) => go(pickCourse(answers, courses?.find((x) => x.code === c.code) ?? c, rated ?? [], new Date()), 'otherCourse')}
            onBack={back}
          />
        );
      case 'term':
        return answers.course && (
          <>
            <TermStep
              professor={answers.professor!}
              course={answers.course}
              selected={answers.term}
              onPick={(t) => choose(answer(answers, { term: t }), 'term')}
              onOther={() => open('otherTerm')}
            />
            <StepFoot onBack={back}>{continueButton(answers.term !== undefined)}</StepFoot>
          </>
        );
      case 'otherTerm':
        return <OtherTermStep now={new Date()} selected={answers.term} onPick={(t) => go(answer(answers, { term: t }), 'otherTerm')} onBack={back} />;
      case 'overall': {
        const options: ChoiceOption<number>[] = OVERALL.map((o) => ({
          value: o.value,
          aria: `${o.value} out of 5, ${o.label}`,
          digit: o.value,
          label: (
            <>
              <span className="rate-n" data-score={o.value}>{o.value}</span>
              <span className="rate-n-label">{o.label}</span>
            </>
          ),
        }));
        return (
          <>
            <ChoiceGroup
              legend={`How was Prof. ${lastName(answers.professor?.name ?? '')} overall?`}
              subtitle="Would you recommend them to a friend?"
              options={options}
              value={answers.rating}
              layout="stack"
              onPick={(v) => choose(answer(answers, { rating: v }), 'overall')}
            />
            <StepFoot onBack={back}>{continueButton(answers.rating !== undefined)}</StepFoot>
          </>
        );
      }
      case 'difficulty': {
        // Scored like the review pills, so Very hard shows red.
        const options: ChoiceOption<number>[] = DIFFICULTY.map((d) => ({
          value: d.value,
          aria: `${d.value} out of 5, ${d.label}`,
          digit: d.value,
          label: (
            <>
              <span className="rate-n" data-score={6 - d.value}>{d.value}</span>
              <span className="rate-n-label">{d.label}</span>
            </>
          ),
        }));
        return (
          <>
            <ChoiceGroup
              legend={`How hard was ${formatCode(answers.course?.code ?? '')}?`}
              subtitle="Exams, assignments, and how hard it was to do well."
              options={options}
              value={answers.difficulty}
              layout="stack"
              onPick={(v) => choose(answer(answers, { difficulty: v }), 'difficulty')}
            />
            <StepFoot onBack={back}>{continueButton(answers.difficulty !== undefined)}</StepFoot>
          </>
        );
      }
      case 'workload':
        return (
          <>
            <ChoiceGroup
              legend="Hours per week outside class?"
              subtitle="Homework, studying, projects. Your best guess is fine."
              options={HOURS.map((h, i) => ({ value: h.value, label: h.label, aria: h.aria, digit: i + 1 }))}
              value={answers.hours}
              layout="stack"
              onPick={(v) => choose(answer(answers, { hours: v }), 'workload')}
            />
            <StepFoot onBack={back}>{continueButton(answers.hours !== undefined)}</StepFoot>
          </>
        );
      case 'grade':
        return (
          <>
            <ChoiceGroup
              legend="What grade did you get?"
              subtitle="Helps students see how this course is graded."
              options={GRADES.map((g) => ({ value: g, label: g, aria: gradeAria(g) }))}
              value={answers.grade ?? undefined}
              layout="grid"
              onPick={(v) => choose(answer(answers, { grade: v }), 'grade')}
            />
            <button
              type="button"
              className={`rate-ghost${answers.grade === null ? ' on' : ''}`}
              aria-pressed={answers.grade === null}
              onClick={() => go(answer(answers, { grade: null }), 'grade')}
            >
              Prefer not to say
            </button>
            <StepFoot onBack={back}>{continueButton(answers.grade !== undefined)}</StepFoot>
          </>
        );
      case 'comment':
        return (
          <CommentStep
            value={answers.comment}
            onChange={(comment) => setAnswers((a) => ({ ...a, comment }))}
            onSubmit={submit}
            onBack={back}
            submitting={locked}
            updating={!!answers.updating}
            error={submitError}
          />
        );
      case 'thanks':
        return <ThanksStep answers={answers} counter={counter} onRateAnother={rateAnother} popperSlot={<Celebration />} />;
      default:
        return null;
    }
  };

  const tags = contextTags(answers);
  const locked = sending || pending !== null;
  const canBack = prevStep(step, answers) !== null;
  const host = window.location.hostname;

  return (
    <div className={`rate-page${cleared ? '' : ' rate-page-check'}`}>
      <div className="rate-shell">
        <div className="rate-panel" ref={panelRef}>
          {cleared && <ProgressBar index={progressIndex(step)} done={step === 'thanks'} />}
          {startFailed && <p className="rate-hint" role="alert">We couldn't start the form. Please reload and try again.</p>}
          {cleared && ready && step !== 'thanks' && (
            <div className="rate-top">
              <button type="button" className={`rate-back-top${canBack ? '' : ' is-hidden'}`} disabled={locked} onClick={back}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M19 12H5" /><path d="m12 19-7-7 7-7" /></svg>
                Back
              </button>
              {(tags.length > 0 || answers.updating) && (
                <div className="rate-tags">
                  {answers.updating && <span className="rate-tag is-updating">Updating</span>}
                  {tags.map((t) => <span key={t} className="rate-tag">{t}</span>)}
                </div>
              )}
            </div>
          )}
          {cleared && ready && <Fragment key={step}>{renderStep()}</Fragment>}
          {!cleared && (
            <div className="rate-check">
              <h1 className="rate-check-host" tabIndex={-1}>{host}</h1>
              {failed ? (
                <p className="rate-error" role="alert">We couldn't verify your browser. Try turning off a VPN or ad blocker, then try again.</p>
              ) : (
                <p className="rate-check-lead" role="status">Verifying you are human. This may take a few seconds.</p>
              )}
            </div>
          )}
          {/* One container in one place for the whole visit, so the widget survives the checkpoint giving way to the form. */}
          <div ref={containerRef} className={`rate-turnstile${cleared && !interactive ? ' is-done' : ''}`} />
          {!cleared && (
            <div className="rate-check">
              {/* A reload, since a blocked script never rendered a widget to reset; nothing is filled in yet to lose. */}
              {failed && <button type="button" className="rate-check-retry" onClick={() => window.location.reload()}>Try again</button>}
              <p className="rate-check-note">{host} needs to review the security of your connection before you can rate.</p>
              <p className="rate-check-foot">Protected by Cloudflare Turnstile</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
