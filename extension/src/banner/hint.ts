/** A one-time note the first time ratings appear on Banner, so a student who
 *  just switched the feature on knows it's working and that a rating opens
 *  more. Shown once per browser, never again; the only thing stored is that
 *  it was shown. */

const SEEN_KEY = 'rmh:banner-hint-seen';
const SHOW_MS = 9000;

const STYLE = `
  :host { all: initial; position: fixed; right: 16px; bottom: 16px; z-index: 2147483647; }
  .hint {
    display: flex; align-items: flex-start; gap: 10px; max-width: 300px;
    padding: 10px 12px; border-radius: 10px; background: #16181d; color: #fff;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.25);
    font: 500 12.5px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  b { color: #ff8a96; }
  button {
    flex: none; padding: 0 2px; border: 0; background: none; color: #a2a8b4;
    font: inherit; font-size: 14px; line-height: 1; cursor: pointer;
  }
  button:hover { color: #fff; }
  button:focus-visible { outline: 2px solid #ff8a96; outline-offset: 2px; border-radius: 3px; }
`;

let checked = false;

/** Call whenever a rating badge is placed; it does nothing after the first. */
export async function maybeShowHint(): Promise<void> {
  if (checked) return;
  checked = true;
  try {
    const seen = (await chrome.storage.local.get(SEEN_KEY))[SEEN_KEY];
    if (seen) return;
    await chrome.storage.local.set({ [SEEN_KEY]: true });
  } catch {
    // No storage, no hint: better silent than shown on every page load.
    return;
  }

  const host = document.createElement('rmh-hint');
  const style = document.createElement('style');
  style.textContent = STYLE;
  const box = document.createElement('div');
  box.className = 'hint';
  box.setAttribute('role', 'status');
  const text = document.createElement('span');
  const brand = document.createElement('b');
  brand.textContent = 'RateMyHusky';
  text.append(brand, ' ratings are on. Click any rating to see the professor’s reviews.');
  const close = document.createElement('button');
  close.type = 'button';
  close.textContent = '✕';
  close.setAttribute('aria-label', 'Dismiss');
  close.addEventListener('click', () => host.remove());
  box.append(text, close);
  host.attachShadow({ mode: 'open' }).append(style, box);
  document.body.append(host);
  window.setTimeout(() => host.remove(), SHOW_MS);
}
