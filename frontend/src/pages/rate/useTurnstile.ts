import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY;
// Without a site key there's no widget to wait for; the backend skips the check when it has no secret either.
const NO_WIDGET_TOKEN = 'no-turnstile';
// An ad blocker or network filter can stop the script from ever loading.
const SCRIPT_WAIT_MS = 10000;

export function useTurnstile(): { containerRef: RefObject<HTMLDivElement | null>; token: string; failed: boolean; interactive: boolean; reset: () => void } {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const [token, setToken] = useState('');
  const [failed, setFailed] = useState(false);
  const [interactive, setInteractive] = useState(false);

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY) return;
    // Wait for the Turnstile script to load, as FeedbackTab does.
    const giveUp = setTimeout(() => {
      clearInterval(interval);
      setFailed(true);
    }, SCRIPT_WAIT_MS);
    const interval = setInterval(() => {
      if (!window.turnstile || !containerRef.current) return;
      clearInterval(interval);
      clearTimeout(giveUp);
      const id = window.turnstile.render(containerRef.current, {
        sitekey: TURNSTILE_SITE_KEY,
        // Rate hides the box unless a click is needed.
        appearance: 'always',
        callback: (t: string) => {
          setToken(t);
          setFailed(false); // an automatic retry recovered from an earlier error
        },
        'error-callback': () => setFailed(true),
        'before-interactive-callback': () => setInteractive(true),
        'after-interactive-callback': () => setInteractive(false),
        'expired-callback': () => {
          setToken('');
          window.turnstile?.reset(id);
        },
        theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
      });
      widgetIdRef.current = id;
    }, 100);
    return () => {
      clearInterval(interval);
      clearTimeout(giveUp);
      if (widgetIdRef.current !== null && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
      setToken('');
    };
  }, []);

  // A script that never loaded has no widget to retry, so it stays failed and Rate says why at once.
  const reset = useCallback(() => {
    setToken('');
    if (widgetIdRef.current === null) return;
    setFailed(false);
    window.turnstile?.reset(widgetIdRef.current);
  }, []);

  return { containerRef, token: TURNSTILE_SITE_KEY ? token : NO_WIDGET_TOKEN, failed, interactive, reset };
}
