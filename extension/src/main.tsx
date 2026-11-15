import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { applyTheme, loadTheme } from './utils/theme';
import { OPEN_KEY } from './banner/messages';
// Bundled, not fetched from Google: a popup opens often, and a remote font
// means a late paint plus a request to a third party on every open.
import '@fontsource/nunito/latin-400.css';
import '@fontsource/nunito/latin-700.css';
import '@fontsource/nunito/latin-900.css';
import './styles/tokens.css';
import './styles/buttons.css';
import './styles/section.css';

// Before the first paint, not in an effect: a popup is small enough that a
// render at the OS theme followed by a correction is a visible flash.
applyTheme(loadTheme());

/** The professor a Banner badge click opened the popup for, if any. Taken
 *  once and cleared, so the next time the toolbar icon opens the popup it
 *  starts on Search as usual. Read before the first render rather than in an
 *  effect, or the popup would flash Search and then jump. */
async function takeOpenRequest(): Promise<string | undefined> {
  try {
    const session = chrome.storage.session;
    const slug = (await session.get(OPEN_KEY))[OPEN_KEY];
    await session.remove(OPEN_KEY);
    return typeof slug === 'string' ? slug : undefined;
  } catch {
    // Outside the extension (a Vite preview) there's no chrome.storage.
    return undefined;
  }
}

void takeOpenRequest().then((openSlug) =>
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App openSlug={openSlug} />
    </StrictMode>,
  ),
);
