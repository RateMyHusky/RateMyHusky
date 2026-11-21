import { useEffect, useRef, type RefObject } from 'react';
import { MIN_DWELL_MS } from './ratePrompt';

// Fires once per mount after delayMs of visible time, or after minMs of visible time once a scroll
// leaves the section's top above the bottom 15% of the screen. delayMs null means not armed yet.
export function useDwell(
  sectionRef: RefObject<HTMLElement | null>,
  delayMs: number | null,
  onFire: (signal: 'time' | 'scroll') => void,
  minMs: number = MIN_DWELL_MS,
) {
  const onFireRef = useRef(onFire);
  useEffect(() => { onFireRef.current = onFire; });

  useEffect(() => {
    if (delayMs === null) return;

    // Dwell counts visible time only, so a background tab never fires.
    let fired = false;
    let timer: number | undefined;
    let scrolled = false;
    let visibleMs = 0;
    let visibleSince: number | null = document.visibilityState === 'visible' ? Date.now() : null;

    const fire = (signal: 'time' | 'scroll') => {
      if (fired) return;
      fired = true;
      onFireRef.current(signal);
    };

    const schedule = () => {
      window.clearTimeout(timer);
      if (fired || visibleSince === null) return;
      const seen = visibleMs + (Date.now() - visibleSince);
      if (scrolled && seen >= minMs) return fire('scroll');
      if (seen >= delayMs) return fire('time');
      timer = window.setTimeout(schedule, (scrolled ? Math.min(delayMs, minMs) : delayMs) - seen);
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

    // Counts on a scroll that leaves the section's top above the bottom 15% of the screen. A section already
    // on screen at load waits for a scroll, so a tall window can't fire 'scroll' with no scrolling.
    const el = sectionRef.current;
    const onScroll = () => {
      if (!el || el.getBoundingClientRect().top > window.innerHeight * 0.85) return;
      window.removeEventListener('scroll', onScroll);
      scrolled = true;
      schedule();
    };
    if (el) window.addEventListener('scroll', onScroll, { passive: true });

    schedule();

    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('scroll', onScroll);
    };
  }, [sectionRef, delayMs, minMs]);
}
