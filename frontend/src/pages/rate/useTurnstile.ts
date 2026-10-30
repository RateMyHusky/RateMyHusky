import { useCallback, useEffect, useRef, useState } from 'react';

const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY;
// Without a site key there's no widget to wait for; the backend skips the check when it has no secret either.
const NO_WIDGET_TOKEN = 'no-turnstile';
// An ad blocker or network filter can stop the script from ever loading.
const SCRIPT_WAIT_MS = 10000;
const SCRIPT_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
// The framed box (Rate.css .rate-verify.is-on) is 2px wider than Cloudflare's 300px one.
const NORMAL_MIN_WIDTH = 302;

// The check runs only while `containerRef` is attached (the last step), so a click, when Cloudflare
// needs one, is asked for next to Submit and the token is fresh when it's sent.
export function useTurnstile(): {
  containerRef: (el: HTMLDivElement | null) => void; token: string; failed: boolean; scriptFailed: boolean; interactive: boolean; reset: () => void;
} {
  const [container, containerRef] = useState<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const [loaded, setLoaded] = useState(() => !!window.turnstile);
  const [scriptFailed, setScriptFailed] = useState(false);
  // Bumped by reset() after the script failed, to request it again (index.html requests it once).
  const [scriptAttempt, setScriptAttempt] = useState(0);
  const [widgetFailed, setWidgetFailed] = useState(false);
  const [token, setToken] = useState('');
  const [interactive, setInteractive] = useState(false);
  const [size, setSize] = useState<'normal' | 'compact' | null>(null);

  // Watched from page load, so a blocked script is already known by the last step. Polling keeps on
  // past the wait, so a script that arrives late (a slow phone) still recovers without a reload. A retry
  // adds a fresh <script>, so once the student turns off the blocker the widget renders with answers kept.
  useEffect(() => {
    if (!TURNSTILE_SITE_KEY || loaded) return;
    if (scriptAttempt > 0) {
      const script = document.createElement('script');
      script.src = SCRIPT_SRC;
      script.async = true;
      document.head.appendChild(script);
    }
    const giveUp = setTimeout(() => setScriptFailed(true), SCRIPT_WAIT_MS);
    const interval = setInterval(() => {
      if (!window.turnstile) return;
      clearInterval(interval);
      clearTimeout(giveUp);
      setScriptFailed(false);
      setLoaded(true);
    }, 100);
    return () => {
      clearInterval(interval);
      clearTimeout(giveUp);
    };
  }, [loaded, scriptAttempt]);

  // Measured on the column, not the box, which shrinks to the widget once it shows. A phone rotated
  // across the line renders the widget again at the size that fits.
  useEffect(() => {
    const column = container?.parentElement;
    if (!column) return;
    const measure = () => setSize(column.clientWidth >= NORMAL_MIN_WIDTH ? 'normal' : 'compact');
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(column);
    return () => observer.disconnect();
  }, [container]);

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY || !loaded || !container || !size || !window.turnstile) return;
    const id = window.turnstile.render(container, {
      sitekey: TURNSTILE_SITE_KEY,
      // Cloudflare shows the box only when it needs a click. A fixed size, since 'flexible' stays at 300px
      // on phones anyway; the compact one fits a column narrower than that.
      appearance: 'interaction-only',
      size,
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
  }, [loaded, container, size]);

  // A script that never loaded has no widget to retry, so the script itself is requested again.
  const reset = useCallback(() => {
    setToken('');
    if (widgetIdRef.current === null) {
      if (TURNSTILE_SITE_KEY && !window.turnstile) {
        setScriptFailed(false);
        setScriptAttempt((n) => n + 1);
      }
      return;
    }
    setWidgetFailed(false);
    window.turnstile?.reset(widgetIdRef.current);
  }, []);

  return {
    containerRef, token: TURNSTILE_SITE_KEY ? token : NO_WIDGET_TOKEN, failed: scriptFailed || widgetFailed, scriptFailed, interactive, reset,
  };
}
