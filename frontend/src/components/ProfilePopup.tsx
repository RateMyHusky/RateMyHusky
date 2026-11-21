import { useEffect, useRef, useState, type RefObject } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { saveProfile } from '../api/api';
import { useProfileStatus } from '../hooks/useProfileStatus';
import { markProfileSaved } from '../utils/profileStatus';
import {
  loadState, saveState, canShowProfilePrompt, markShown, markDismissed, markResume, takeResume,
  gradYearOptions, isLastQuestion, canAdvance, toAnswers, PROFILE_DWELL_MS, PROFILE_SCROLL_DWELL_MS,
  type Step, type YearChoice, type RateGate,
} from '../utils/profilePrompt';
import { useDwell } from '../utils/useDwell';
import { track } from '../utils/ratePrompt';
import type { Program } from '../utils/programSearch';
import ProgramPicker from './ProgramPicker';
import SignInModal from './SignInModal';
import './RatePopup.css';
import './ProfilePopup.css';

interface Props {
  sectionRef: RefObject<HTMLElement | null>;
  gate: RateGate;
  onOpen?: () => void;
}

interface Lists { majors: Program[]; minors: Program[] }

export default function ProfilePopup({ sectionRef, gate, onOpen }: Props) {
  const { user, loading } = useAuth();
  const status = useProfileStatus();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  // Once opened the dwell never re-arms, whatever happens to eligibility afterwards.
  const [launched, setLaunched] = useState(false);
  const [step, setStep] = useState<Step>(1);
  const [year, setYear] = useState<YearChoice>(null);
  const [majors, setMajors] = useState<string[]>([]);
  const [minors, setMinors] = useState<string[]>([]);
  const [lists, setLists] = useState<Lists | null>(null);
  const [signInOpen, setSignInOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const [listsFailed, setListsFailed] = useState(false);
  const waitingForGate = useRef(false);
  const resumeChecked = useRef(false);
  const resumed = useRef<ReturnType<typeof takeResume>>(null);
  // The save after a sign-in runs once; a failure leaves a Try again button instead of retrying on its own.
  const autoSaved = useRef(false);

  const eligible = !loading && (!user || (!!status && !status.exists));
  const clearResume = () => { takeResume(pathname, Date.now()); };

  // The dwell fired and the rate popup is out of the way: apply the cooldowns, then open.
  const tryShow = () => {
    const state = loadState();
    if (!state || !canShowProfilePrompt(state, Date.now())) return;
    saveState(markShown(state, Date.now()));
    setStep(1);
    setOpen(true);
    setLaunched(true);
    track('profile_prompt_shown', {});
  };

  const save = async () => {
    setSaving(true);
    setFailed(false);
    try {
      await saveProfile(toAnswers(year, majors, minors));
      markProfileSaved();
      track('profile_prompt_finished', {});
      setOpen(false);
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  useDwell(sectionRef, eligible && !launched ? PROFILE_DWELL_MS : null, () => {
    if (gate === 'shown') return;
    if (gate === 'pending') {
      waitingForGate.current = true;
      return;
    }
    tryShow();
  }, PROFILE_SCROLL_DWELL_MS);

  // A dwell that fired while the rate popup was undecided opens once that popup is known to stay away.
  useEffect(() => {
    if (!waitingForGate.current || gate === 'pending') return;
    waitingForGate.current = false;
    // The student may have signed in while waiting, into an account that already has a profile.
    if (gate === 'clear' && eligible) tryShow();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gate]);

  // Back from the phone's Google redirect, or from the FAQ after signing in there: reopen at the
  // sign-in step with the answers, which saves them below. No dwell, cooldown or new shown mark.
  useEffect(() => {
    if (loading) return;
    // Taken on the first check whatever the auth state, so a marker that isn't used here doesn't linger.
    if (!resumeChecked.current) {
      resumeChecked.current = true;
      resumed.current = takeResume(pathname, Date.now());
    }
    // The user can arrive later in this mount, after an /api/auth/me retry.
    const answers = resumed.current;
    if (!answers || !user || status === undefined) return;
    resumed.current = null;
    // The rate popup may have opened while the status loaded.
    if (status && !status.exists && gate !== 'shown') {
      setYear(answers.year);
      setMajors(answers.majors);
      setMinors(answers.minors);
      setStep(4);
      setOpen(true);
      setLaunched(true);
    }
  }, [loading, user, status, pathname, gate]);

  // Signed in at the sign-in step: save the answers, or close if the account already has a profile.
  useEffect(() => {
    if (!open || step !== 4 || !user || status === undefined || autoSaved.current) return;
    autoSaved.current = true;
    takeResume(pathname, Date.now());
    if (status && !status.exists) void save();
    else setOpen(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, step, user, status, pathname]);

  useEffect(() => {
    if (open) onOpen?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (open) track('profile_prompt_step', { step: String(step) });
  }, [open, step]);

  useEffect(() => {
    if (!open || lists) return;
    let cancelled = false;
    import('../data/programs.json').then((m) => {
      if (!cancelled) setLists({ majors: m.majors, minors: m.minors });
    }).catch(() => {
      if (!cancelled) setListsFailed(true);
    });
    return () => { cancelled = true; };
  }, [open, lists]);

  // The live region stays mounted while empty: screen readers announce content added to an
  // existing region, not a region that arrives already filled.
  if (!open) return <><div key="live" aria-live="polite" /></>;

  const dismiss = () => {
    const state = loadState();
    // With the program list unavailable there was no way forward, so leaving isn't counted as a skip.
    if (state && !listsFailed) saveState(markDismissed(state, Date.now()));
    track('profile_prompt_dismissed', { step: String(step) });
    clearResume();
    setOpen(false);
  };

  const lastQuestion = step !== 4 && isLastQuestion(step, year);
  // Signed out, the last question leads to the sign-in step; signed in, it saves.
  const next = () => {
    if (!lastQuestion) setStep((step + 1) as Step);
    else if (user) void save();
    else setStep(4);
  };
  const savesHere = step === 4 || (lastQuestion && !!user);

  const title = {
    1: 'Help us find the best classes for your major',
    2: "What's your major?",
    3: 'Any minors? (optional)',
    4: user ? 'Saving your answers' : 'Sign in to save',
  }[step];

  return (
    <>
      <div key="live" aria-live="polite">
      <div className="rate-popup profile-popup" role="region" aria-label="Course picks">
        {step !== 4 && (
          <div className="profile-dots" role="img" aria-label={`Step ${step} of 3`}>
            {[1, 2, 3].map((n) => <i key={n} className={n <= step ? 'on' : undefined} />)}
          </div>
        )}
        <p className="rate-popup-text">{title}</p>

        {step === 1 && (
          <>
            <p className="profile-sub">Tell us your year and major. It takes 15 seconds.</p>
            <span className="profile-label" id="profile-year-label">Expected graduation year</span>
            <div className="profile-years" role="group" aria-labelledby="profile-year-label">
              {[...gradYearOptions(Date.now()), 'grad' as const].map((y) => (
                <button
                  type="button"
                  key={y}
                  className={y === year ? 'profile-year on' : 'profile-year'}
                  aria-pressed={y === year}
                  onClick={() => setYear(y)}
                >
                  {y === 'grad' ? 'Grad student' : y}
                </button>
              ))}
            </div>
          </>
        )}
        {(step === 2 || step === 3) && (
          <div aria-live="off">
          {lists ? (
          <ProgramPicker
            key={step}
            label={step === 2 ? 'Major' : 'Minor'}
            programs={step === 2 ? lists.majors : lists.minors}
            selected={step === 2 ? majors : minors}
            onChange={step === 2 ? setMajors : setMinors}
            addLabel={step === 2 ? '+ Add another major' : '+ Add another minor'}
            otherLabel={step === 2 ? "My major isn't listed" : "My minor isn't listed"}
          />
          ) : !listsFailed && <p className="profile-loading">Loading…</p>}
          </div>
        )}
        {step === 4 && !user && (
          <p className="profile-sub">Use your Husky account. We'll use your answers to suggest courses.</p>
        )}

        {savesHere && (
          <p className="profile-note">
            Your activity here helps tailor picks. <a href="/privacy#course-picks" target="_blank" rel="noopener noreferrer">Learn more</a>
          </p>
        )}
        {listsFailed && <p className="profile-error" role="alert">Couldn't load the program list. Try again later.</p>}
        {failed && <p className="profile-error" role="alert">Couldn't save that. Try again.</p>}

        {step === 4 ? (
          <button
            type="button"
            className="profile-btn"
            // Signed in, the save starts on its own; the button only retries one that failed.
            disabled={saving || (!!user && !failed)}
            onClick={() => {
              if (user) { void save(); return; }
              markResume(pathname, { year, majors, minors });
              setSignInOpen(true);
            }}
          >
            {user ? (failed ? 'Try again' : 'Saving…') : 'Sign in'}
          </button>
        ) : (
          <div className="profile-row">
            <button
              type="button"
              className="profile-btn"
              disabled={!canAdvance(step, year, majors) || saving}
              onClick={next}
            >
              {lastQuestion && user ? 'Done' : 'Next'}
            </button>
          </div>
        )}
        <button type="button" className="rate-popup-later" onClick={dismiss}>Skip for now</button>
      </div>
      </div>
      <SignInModal
        key="signin"
        open={signInOpen}
        // Leaving through the FAQ, Terms or Privacy link keeps the resume marker, so signing in
        // there and coming back to this page within 15 minutes saves the answers.
        onClose={(leaving) => { setSignInOpen(false); if (!leaving) clearResume(); }}
        reason="Sign in to save your answers."
      />
    </>
  );
}
