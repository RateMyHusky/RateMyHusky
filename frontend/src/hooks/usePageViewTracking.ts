import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import { sendPageView } from '../api/api';
import { makeSender, setVisible, startTimer, viewToSend, visibleSeconds } from '../utils/pageView';

interface Options {
  itemType: 'professor' | 'course';
  itemKey: string | null;
  sectionRef: RefObject<HTMLElement | null>;
  courseFilter: string | null;
  enabled: boolean | undefined;
}

/* Records one view per itemKey: visible seconds, whether the section was reached, the course filter.
   `enabled` is decided once per view, by its first non-undefined value. */
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
    const send = makeSender(sendPageView);
    const flush = () => {
      if (!decided.current.enabled) return;
      send(viewToSend(
        { itemType, itemKey, reachedSection: reached, courseFilter: decided.current.filter },
        visibleSeconds(timer, Date.now()),
      ));
    };

    const el = sectionRef.current;
    const observer = el ? new IntersectionObserver((entries) => {
      if (entries.some(e => e.isIntersecting)) reached = true;
    }) : null;
    if (el && observer) observer.observe(el);

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
      observer?.disconnect();
      flush();
    };
  }, [itemType, itemKey, sectionRef]);
}
