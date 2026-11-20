import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import { sendPageView } from '../api/api';
import { cutView, setVisible, startTimer } from '../utils/pageView';

interface Options {
  itemType: 'professor' | 'course';
  itemKey: string | null;
  sectionRef: RefObject<HTMLElement | null>;
  courseFilter: string | null;
  enabled: boolean | undefined;
}

const IDLE_MS = 60_000;
// The student's own input: these mark them as present, and only a scroll after one counts as reaching the section.
const INTENT_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const;

/* Records views of an itemKey: active visible seconds, whether the section was reached, the course filter.
   A view is sent when the page is hidden or left; time after the student comes back is sent as the next one.
   `enabled` is decided once per itemKey, by its first non-undefined value. */
export function usePageViewTracking({ itemType, itemKey, sectionRef, courseFilter, enabled }: Options): void {
  const decided = useRef<{ key: string | null; enabled: boolean | undefined; filter: string | null }>({ key: null, enabled: undefined, filter: null });

  useEffect(() => {
    // The filter is frozen with the view's start, so a later URL change cannot leak into it.
    if (decided.current.key !== itemKey) decided.current = { key: itemKey, enabled: undefined, filter: courseFilter };
    if (decided.current.enabled === undefined && enabled !== undefined) decided.current.enabled = enabled;
  });

  useEffect(() => {
    if (itemKey === null) return;
    let visible = document.visibilityState === 'visible';
    let idle = false;
    let lastInput = Date.now();
    let idleCheck: number | undefined;
    let timer = startTimer(Date.now(), visible);
    let reached = false;
    const flush = () => {
      if (!decided.current.enabled) return;
      const cut = cutView(timer, Date.now(), visible && !idle,
        { itemType, itemKey, reachedSection: reached, courseFilter: decided.current.filter });
      timer = cut.timer;
      if (cut.view) sendPageView(cut.view);
    };

    // A visible page with no input for IDLE_MS stops counting until the next input, so a tab left open isn't reading time.
    const checkIdle = () => {
      const left = lastInput + IDLE_MS - Date.now();
      if (left > 0) {
        idleCheck = window.setTimeout(checkIdle, left);
        return;
      }
      idle = true;
      timer = setVisible(timer, false, Date.now());
    };
    const wake = () => {
      lastInput = Date.now();
      if (!visible || !idle) return;
      idle = false;
      timer = setVisible(timer, true, lastInput);
      idleCheck = window.setTimeout(checkIdle, IDLE_MS);
    };
    if (visible) idleCheck = window.setTimeout(checkIdle, IDLE_MS);

    // Reached only on a scroll after the student's own input, so a section already on screen at load,
    // an automatic scroll (an Ask citation) or a restored scroll position doesn't count.
    let interacted = false;
    let inView = false;
    let scrolled = false;
    const el = sectionRef.current;
    const observer = el ? new IntersectionObserver((entries) => {
      inView = entries[entries.length - 1].isIntersecting;
      if (inView && scrolled) reached = true;
    }) : null;
    if (el && observer) observer.observe(el);
    const onScroll = () => {
      if (!interacted) return;
      wake();
      scrolled = true;
      if (inView) reached = true;
    };
    const onIntent = (e: Event) => {
      if (!e.isTrusted) return;
      interacted = true;
      wake();
    };
    const onMove = (e: Event) => {
      if (e.isTrusted) wake();
    };
    for (const type of INTENT_EVENTS) window.addEventListener(type, onIntent, { passive: true });
    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('scroll', onScroll, { passive: true });

    const onVisibility = () => {
      visible = document.visibilityState === 'visible';
      window.clearTimeout(idleCheck);
      if (visible) {
        // Coming back to the tab counts as input.
        idle = false;
        lastInput = Date.now();
        timer = setVisible(timer, true, lastInput);
        idleCheck = window.setTimeout(checkIdle, IDLE_MS);
      } else {
        timer = setVisible(timer, false, Date.now());
        flush();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', flush);
    return () => {
      window.clearTimeout(idleCheck);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', flush);
      for (const type of INTENT_EVENTS) window.removeEventListener(type, onIntent);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('scroll', onScroll);
      observer?.disconnect();
      flush();
    };
  }, [itemType, itemKey, sectionRef]);
}
