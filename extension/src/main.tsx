import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
// Bundled, not fetched from Google: a popup opens often, and a remote font
// means a late paint plus a request to a third party on every open.
import '@fontsource/nunito/latin-400.css';
import '@fontsource/nunito/latin-700.css';
import '@fontsource/nunito/latin-900.css';
import './styles/tokens.css';
import './styles/buttons.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
