import { useEffect, useRef, useState, type RefObject } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { saveProfile } from '../api/api';
import { useProfileStatus } from '../hooks/useProfileStatus';
import { markProfileSaved } from '../utils/profileStatus';
import {
  loadState, saveState, canShowProfilePrompt, markShown, markDismissed, markResume, takeResume,
  gradYearOptions, firstStep, isLastStep, canAdvance, toAnswers, type Step, type YearChoice, type RateGate,
} from '../utils/profilePrompt';
import { useDwell } from '../utils/useDwell';
import { DWELL_MS, track } from '../utils/ratePrompt';
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
  const waitingForGate = useRef(false);
  const resumeChecked = useRef(false);
  const resumePending = useRef(false);

  const eligible = !loading && (!user || (!!status && !status.exists));
  const clearResume = () => { takeResume(pathname, Date.now()); };

  // The dwell fired and the rate popup is out of the way: apply the cooldowns, then open.
  const tryShow = () => {
    const state = loadState();
    if (!state || !canShowProfilePrompt(state, Date.now())) return;
    saveState(markShown(state, Date.now()));
    setStep(firstStep(!!user));
    setOpen(true);
    setLaunched(true);
    track('profile_prompt_shown', {});
  };

  useDwell(sectionRef, eligible && !launched ? DWELL_MS : null, () => {
    if (gate === 'shown') return;
    if (gate === 'pending') {
      waitingForGate.current = true;
      return;
    }
    tryShow();
  });

  // A dwell that fired while the rate popup was undecided opens once that popup is known to stay away.
  useEffect(() => {
    if (!waitingForGate.current || gate === 'pending') return;
    waitingForGate.current = false;
    // The student may have signed in while waiting, into an account that already has a profile.
    if (gate === 'clear' && eligible) tryShow();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gate]);

  // Back from the mobile Google redirect: continue at step 1 with no dwell, cooldown or new shown mark.
  useEffect(() => {
    if (loading) return;
    if (!resumeChecked.current) {
      resumeChecked.current = true;
      if (user && takeResume(pathname, Date.now())) resumePending.current = true;
    }
    if (!resumePending.current || status === undefined) return;
    resumePending.current = false;
    if (status && !status.exists) {
      setStep(1);
      setOpen(true);
      setLaunched(true);
    }
  }, [loading, user, status, pathname]);

  // Signed in at step 0: an existing profile means nothing to ask; otherwise carry on to the year.
  useEffect(() => {
    if (!open || step !== 0 || !user || status === undefined) return;
    takeResume(pathname, Date.now());
    if (status && !status.exists) setStep(1);
    else setOpen(false);
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
    });
    return () => { cancelled = true; };
  }, [open, lists]);

  // The live region stays mounted while empty: screen readers announce content added to an
  // existing region, not a region that arrives already filled.
  if (!open) return <div aria-live="polite" />;

  const dismiss = () => {
    const state = loadState();
    if (state) saveState(markDismissed(state, Date.now()));
    track('profile_prompt_dismissed', { step: String(step) });
    clearResume();
    setOpen(false);
  };

  const save = async (withMinors: string[]) => {
    setSaving(true);
    setFailed(false);
    try {
      await saveProfile(toAnswers(year, majors, withMinors));
      markProfileSaved();
      track('profile_prompt_finished', {});
      setOpen(false);
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  const last = isLastStep(step, year);
  const next = () => (last ? save(minors) : setStep((step + 1) as Step));

  const title = [
    'Sign in with your Husky account to get course picks',
    'When do you expect to graduate?',
    "What's your major?",
    'Any minors? (optional)',
  ][step];

  return (
    <div aria-live="polite">
      <div className="rate-popup profile-popup" role="region" aria-label="Course picks">
        {step > 0 && (
          <div className="profile-dots" role="img" aria-label={`Step ${step} of 3`}>
            {[1, 2, 3].map((n) => <i key={n} className={n <= step ? 'on' : undefined} />)}
          </div>
        )}
        <p className="rate-popup-text">{title}</p>

        {step === 1 && (
          <div className="profile-years">
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
        )}
        {(step === 2 || step === 3) && (lists ? (
          <ProgramPicker
            key={step}
            label={step === 2 ? 'Major' : 'Minor'}
            programs={step === 2 ? lists.majors : lists.minors}
            selected={step === 2 ? majors : minors}
            onChange={step === 2 ? setMajors : setMinors}
            addLabel={step === 2 ? '+ Add another major' : '+ Add another minor'}
            otherLabel={step === 2 ? "My major isn't listed" : "My minor isn't listed"}
          />
        ) : <p className="profile-loading">Loading…</p>)}

        {last && (
          <p className="profile-note">
            Your activity here helps tailor picks. <Link to="/privacy#course-picks">Learn more</Link>
          </p>
        )}
        {failed && <p className="profile-error" role="alert">Couldn't save that. Try again.</p>}

        {step === 0 ? (
          <button
            type="button"
            className="profile-btn"
            onClick={() => { markResume(pathname); setSignInOpen(true); }}
          >
            Sign in
          </button>
        ) : (
          <div className="profile-row">
            {step === 3 && (
              <button type="button" className="profile-ghost" disabled={saving} onClick={() => save([])}>Skip</button>
            )}
            <button
              type="button"
              className="profile-btn"
              disabled={!canAdvance(step, year, majors) || saving}
              onClick={next}
            >
              {last ? 'Done' : 'Next'}
            </button>
          </div>
        )}
        {step < 3 && <button type="button" className="rate-popup-later" onClick={dismiss}>Skip for now</button>}
      </div>
      <SignInModal
        open={signInOpen}
        onClose={() => { setSignInOpen(false); clearResume(); }}
        reason="Sign in to get course picks."
      />
    </div>
  );
}
