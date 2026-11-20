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

/* Records views of an itemKey: visible seconds, whether the section was reached, the course filter.
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
    let timer = startTimer(Date.now(), document.visibilityState === 'visible');
    let reached = false;
    const flush = () => {
      if (!decided.current.enabled) return;
      const cut = cutView(timer, Date.now(), document.visibilityState === 'visible',
        { itemType, itemKey, reachedSection: reached, courseFilter: decided.current.filter });
      timer = cut.timer;
      if (cut.view) sendPageView(cut.view);
    };

    // Reached only once the student scrolls, so a section already on screen at load doesn't count.
    let inView = false;
    let scrolled = false;
    const el = sectionRef.current;
    const observer = el ? new IntersectionObserver((entries) => {
      inView = entries[entries.length - 1].isIntersecting;
      if (inView && scrolled) reached = true;
    }) : null;
    if (el && observer) observer.observe(el);
    const onScroll = () => {
      scrolled = true;
      if (inView) reached = true;
    };
    window.addEventListener('scroll', onScroll, { passive: true });

    const onVisibility = () => {
      const visible = document.visibilityState === 'visible';
      timer = setVisible(timer, visible, Date.now());
      if (!visible) flush();
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', flush);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', flush);
      window.removeEventListener('scroll', onScroll);
      observer?.disconnect();
      flush();
    };
  }, [itemType, itemKey, sectionRef]);
}
