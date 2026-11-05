import { useEffect, useRef } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

const storageKey = (key: string) => `catalog-scroll:${key}`;

function readScroll(key: string): number | null {
  try {
    const raw = sessionStorage.getItem(storageKey(key));
    if (raw === null) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

function writeScroll(key: string, y: number): void {
  try {
    sessionStorage.setItem(storageKey(key), String(y));
  } catch {
    // storage blocked: Back still pages correctly, just without scroll restore
  }
}

// React Router gives the first entry of every full page load the key "default", and sessionStorage outlives
// same-tab navigations, so a fresh load (typed URL, link) must not inherit the previous page's saved scroll.
// Reload and Back from another site keep theirs.
try {
  const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
  if (nav?.type === 'navigate') sessionStorage.removeItem(storageKey('default'));
} catch {
  // storage blocked
}

// Remembers the scroll position per history entry and restores it on Back/Forward once the catalog has loaded.
export function useCatalogScroll(ready: boolean): void {
  const { key } = useLocation();
  const navType = useNavigationType();
  const restored = useRef<string | null>(null);   // the entry whose scroll was already restored

  useEffect(() => {
    if (navType !== 'POP' || !ready || restored.current === key) return;
    restored.current = key;
    const saved = readScroll(key);
    if (saved !== null) window.scrollTo(0, saved);
  }, [key, navType, ready]);

  useEffect(() => {
    // A fresh entry may never fire a scroll event, so record where it starts (ScrollToTop has already run).
    if (navType !== 'POP') writeScroll(key, window.scrollY);
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (navType === 'POP' && restored.current !== key) return;   // restore still pending
        writeScroll(key, window.scrollY);
      });
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => { window.removeEventListener('scroll', onScroll); cancelAnimationFrame(frame); };
  }, [key, navType]);
}
