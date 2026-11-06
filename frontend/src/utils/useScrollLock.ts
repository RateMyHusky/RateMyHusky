import { useEffect } from 'react';

/* Stops the page scrolling while `active`. Locks <html>, not <body>: html has
   overflow-x: clip, so a hidden body becomes its own scroll box at 100% height
   and the page jumps to the top. */
export function useScrollLock(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const root = document.documentElement;
    const prev = root.style.overflow;
    root.style.overflow = 'hidden';
    return () => { root.style.overflow = prev; };
  }, [active]);
}
