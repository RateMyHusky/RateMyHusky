import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { Link } from 'react-router-dom';
import {
  loadState, saveState, canShowPopup, visitDay, markShown, markDismissed,
  popupDelay, triggerFor, rateHref, track, type PromptTrigger,
} from '../utils/ratePrompt';
import { useDwell } from '../utils/useDwell';
import { lastName } from '../pages/rate/rateFlow';
import './RatePopup.css';

interface Props {
  slug: string;
  profName: string;
  reviewsRef: RefObject<HTMLElement | null>;
  cardRef: RefObject<HTMLElement | null>;
  onDecided?: (shown: boolean) => void;
  // The profile popup is already open this page view, so this one stays off.
  suppressed?: boolean;
}

const onScreen = (el: HTMLElement) => {
  const r = el.getBoundingClientRect();
  return r.bottom > 0 && r.top < window.innerHeight;
};

export default function RatePopup({ slug, profName, reviewsRef, cardRef, onDecided, suppressed }: Props) {
  const [trigger, setTrigger] = useState<PromptTrigger | null>(null);
  // Decided once per mount: StrictMode reruns the effect after the first run has saved today's date.
  const revisitRef = useRef<boolean | null>(null);
  const [delay, setDelay] = useState<number | null>(null);
  // Reports the decision once per mount, whichever path reaches it.
  const decidedRef = useRef(false);
  const onDecidedRef = useRef(onDecided);
  useEffect(() => { onDecidedRef.current = onDecided; });
  const decide = useCallback((shown: boolean) => {
    if (decidedRef.current) return;
    decidedRef.current = true;
    onDecidedRef.current?.(shown);
  }, []);

  useEffect(() => {
    const loaded = loadState();
    if (!loaded) {
      decide(false);
      return;
    }
    if (revisitRef.current === null) {
      const visit = visitDay(loaded, Date.now());
      revisitRef.current = visit.revisit;
      saveState(visit.state);
    }
    setDelay(popupDelay(revisitRef.current));
  }, [decide]);

  useDwell(reviewsRef, delay, signal => {
    // The in-tab rate card already asked, so the popup stays off for the rest of this page view.
    // A second ask would also spend one of the 3 dismissals.
    if (suppressed) return decide(false);
    if (cardRef.current && onScreen(cardRef.current)) return decide(false);
    const now = Date.now();
    const current = loadState();
    if (!current || !canShowPopup(current, slug, now)) return decide(false);
    saveState(markShown(current, now));
    const t = triggerFor(signal, revisitRef.current ?? false);
    setTrigger(t);
    track('rate_prompt_shown', { trigger: t });
    decide(true);
  });

  // The live region stays mounted while empty: screen readers announce content added to an
  // existing region, not a region that arrives already filled.
  if (!trigger) return <div aria-live="polite" />;

  const hide = () => setTrigger(null);
  const dismiss = () => {
    const current = loadState();
    if (current) saveState(markDismissed(current, Date.now()));
    track('rate_prompt_dismissed', { trigger });
    hide();
  };

  return (
    <div aria-live="polite">
    <div className="rate-popup" role="region" aria-label="Rate this professor">
      <p className="rate-popup-text">Took Prof. {lastName(profName)}? Help a Husky out and rate them.</p>
      <Link
        to={rateHref(slug, 'popup')}
        className="rate-popup-rate"
        onClick={() => { track('rate_prompt_clicked', { trigger }); hide(); }}
      >
        Rate
      </Link>
      <button type="button" className="rate-popup-later" onClick={dismiss}>Skip for now</button>
    </div>
    </div>
  );
}
