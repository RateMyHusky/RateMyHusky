/* Three-state theme. 'system' deliberately stores no attribute, which hands
   the decision back to the prefers-color-scheme block in tokens.css — so it
   keeps tracking the OS if the user changes it while the popup is open. */

export type Theme = 'system' | 'light' | 'dark';

export const THEMES: { value: Theme; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
];

const KEY = 'rmh-theme';

function isTheme(value: unknown): value is Theme {
  return value === 'system' || value === 'light' || value === 'dark';
}

/** localStorage rather than chrome.storage: it's synchronous, so the theme can
 *  land before the first paint, and it still works when the popup is opened as
 *  a plain tab during development. */
export function loadTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (isTheme(saved)) return saved;
  } catch {
    // Storage can be unavailable; the OS default is a fine answer.
  }
  return 'system';
}

export function saveTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Non-fatal — the choice still holds for as long as the popup is open.
  }
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.dataset.theme = theme;
}
