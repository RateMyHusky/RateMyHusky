import { useCallback, useEffect, useRef, useState } from 'react';

const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY;
// Without a site key there's no widget to wait for; the backend skips the check when it has no secret either.
const NO_WIDGET_TOKEN = 'no-turnstile';
// An ad blocker or network filter can stop the script from ever loading.
const SCRIPT_WAIT_MS = 10000;

// The check runs only while `containerRef` is attached (the last step), so a click, when Cloudflare
// needs one, is asked for next to Submit and the token is fresh when it's sent.
export function useTurnstile(): { containerRef: (el: HTMLDivElement | null) => void; token: string; failed: boolean; interactive: boolean; reset: () => void } {
  const [container, containerRef] = useState<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const [loaded, setLoaded] = useState(() => !!window.turnstile);
  const [scriptFailed, setScriptFailed] = useState(false);
  const [widgetFailed, setWidgetFailed] = useState(false);
  const [token, setToken] = useState('');
  const [interactive, setInteractive] = useState(false);

  // Watched from page load, so a blocked script is already known by the last step.
  useEffect(() => {
    if (!TURNSTILE_SITE_KEY || loaded) return;
    // Wait for the Turnstile script to load, as FeedbackTab does.
    const giveUp = setTimeout(() => {
      clearInterval(interval);
      setScriptFailed(true);
    }, SCRIPT_WAIT_MS);
    const interval = setInterval(() => {
      if (!window.turnstile) return;
      clearInterval(interval);
      clearTimeout(giveUp);
      setLoaded(true);
    }, 100);
    return () => {
      clearInterval(interval);
      clearTimeout(giveUp);
    };
  }, [loaded]);

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY || !loaded || !container || !window.turnstile) return;
    const id = window.turnstile.render(container, {
      sitekey: TURNSTILE_SITE_KEY,
      // Cloudflare shows the box only when it needs a click. A fixed size, since 'flexible' stays at 300px
      // on phones anyway; the compact one fits a column narrower than that.
      appearance: 'interaction-only',
      size: container.clientWidth >= 300 ? 'normal' : 'compact',
      callback: (t: string) => {
        setToken(t);
        setWidgetFailed(false); // an automatic retry recovered from an earlier error
      },
      'error-callback': () => setWidgetFailed(true),
      'before-interactive-callback': () => setInteractive(true),
      'after-interactive-callback': () => setInteractive(false),
      'expired-callback': () => {
        setToken('');
        window.turnstile?.reset(id);
      },
      theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
    });
    widgetIdRef.current = id;
    return () => {
      window.turnstile?.remove(id);
      widgetIdRef.current = null;
      setToken('');
      setWidgetFailed(false);
      setInteractive(false);
    };
  }, [loaded, container]);

  // A script that never loaded has no widget to retry, so it stays failed and Rate says why at once.
  const reset = useCallback(() => {
    setToken('');
    if (widgetIdRef.current === null) return;
    setWidgetFailed(false);
    window.turnstile?.reset(widgetIdRef.current);
  }, []);

  return { containerRef, token: TURNSTILE_SITE_KEY ? token : NO_WIDGET_TOKEN, failed: scriptFailed || widgetFailed, interactive, reset };
}
