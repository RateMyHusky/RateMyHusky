import { useEffect } from 'react';

/* Stops the page scrolling. Locks <html>, not <body>: html has overflow-x: clip,
   so a hidden body becomes its own scroll box at 100% height and the page jumps
   to the top. Counted, so overlapping locks (sign-in modal over the filter
   sidebar) can release in any order: the first lock saves the previous value
   and the last release restores it. */
let locks = 0;
let overflowBeforeLock = '';

export function lockScroll() {
  const root = document.documentElement;
  if (locks++ === 0) {
    overflowBeforeLock = root.style.overflow;
    root.style.overflow = 'hidden';
  }
}

export function unlockScroll() {
  if (--locks === 0) document.documentElement.style.overflow = overflowBeforeLock;
}

export function useScrollLock(active: boolean) {
  useEffect(() => {
    if (!active) return;
    lockScroll();
    return unlockScroll;
  }, [active]);
}
