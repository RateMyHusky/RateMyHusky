import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// React Router keys the first entry of every document "default", so per-entry state such as
// useCatalogScroll's would collide between documents in one tab. Give that entry its own id beside
// the router's key, which stays "default" so pages can still tell a document's first entry. It lives in
// history.state, so reload and Back across documents keep it.
if (!window.history.state?.key && !window.history.state?.entryId) {
  window.history.replaceState({ ...window.history.state, entryId: Math.random().toString(36).slice(2, 10) }, '')
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
