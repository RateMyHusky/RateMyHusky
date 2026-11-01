import { useEffect, useRef, useState, type RefObject } from 'react';
import { Link } from 'react-router-dom';
import {
  loadState, saveState, canShowPopup, visitDay, markShown, markDismissed,
  popupDelay, triggerFor, rateHref, track, MIN_DWELL_MS, type PromptTrigger,
} from '../utils/ratePrompt';
import { lastName } from '../pages/rate/rateFlow';
import './RatePopup.css';

interface Props {
  slug: string;
  profName: string;
  reviewsRef: RefObject<HTMLElement | null>;
}

export default function RatePopup({ slug, profName, reviewsRef }: Props) {
  const [trigger, setTrigger] = useState<PromptTrigger | null>(null);
  // Decided once per mount: StrictMode reruns the effect after the first run has saved today's date.
  const revisitRef = useRef<boolean | null>(null);

  useEffect(() => {
    const loaded = loadState();
    if (!loaded) return;
    if (revisitRef.current === null) {
      const visit = visitDay(loaded, Date.now());
      revisitRef.current = visit.revisit;
      saveState(visit.state);
    }
    const revisit = revisitRef.current;

    // Dwell counts visible time only, so a background tab never shows the popup.
    let fired = false;
    let timer: number | undefined;
    let scrolled = false;
    let visibleMs = 0;
    let visibleSince: number | null = document.visibilityState === 'visible' ? Date.now() : null;

    const fire = (signal: 'time' | 'scroll') => {
      if (fired) return;
      fired = true;
      const now = Date.now();
      const current = loadState();
      if (!current || !canShowPopup(current, slug, now)) return;
      saveState(markShown(current, now));
      const t = triggerFor(signal, revisit);
      setTrigger(t);
      track('rate_prompt_shown', { trigger: t });
    };

    const schedule = () => {
      window.clearTimeout(timer);
      if (fired || visibleSince === null) return;
      const seen = visibleMs + (Date.now() - visibleSince);
      const delay = popupDelay(revisit);
      if (scrolled && seen >= MIN_DWELL_MS) return fire('scroll');
      if (seen >= delay) return fire('time');
      timer = window.setTimeout(schedule, (scrolled ? Math.min(delay, MIN_DWELL_MS) : delay) - seen);
    };

    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        if (visibleSince === null) visibleSince = Date.now();
        schedule();
      } else if (visibleSince !== null) {
        visibleMs += Date.now() - visibleSince;
        visibleSince = null;
        window.clearTimeout(timer);
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    const el = reviewsRef.current;
    const observer = el
      ? new IntersectionObserver(entries => {
          if (!entries.some(e => e.isIntersecting)) return;
          observer?.disconnect();
          scrolled = true;
          schedule();
        }, { threshold: 0.15 })
      : null;
    if (el) observer?.observe(el);

    schedule();

    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
      observer?.disconnect();
    };
  }, [slug, reviewsRef]);

  if (!trigger) return null;

  const hide = () => setTrigger(null);
  const dismiss = () => {
    const current = loadState();
    if (current) saveState(markDismissed(current, Date.now()));
    track('rate_prompt_dismissed', { trigger });
    hide();
  };

  return (
    <div className="rate-popup" role="region" aria-live="polite" aria-label="Rate this professor">
      <button type="button" className="rate-popup-close" aria-label="Close" onClick={dismiss}>
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true">
          <line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" />
        </svg>
      </button>
      <p className="rate-popup-text">Took Prof. {lastName(profName)}? Help a Husky out and rate them.</p>
      <div className="rate-popup-actions">
        <Link
          to={rateHref(slug, 'popup')}
          className="rate-popup-rate"
          onClick={() => { track('rate_prompt_clicked', { trigger }); hide(); }}
        >
          Rate
        </Link>
        <button type="button" className="rate-popup-later" onClick={dismiss}>Maybe later</button>
      </div>
    </div>
  );
}
