import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { applyTheme, loadTheme } from './utils/theme';
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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
