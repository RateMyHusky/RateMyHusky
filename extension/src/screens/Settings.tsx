import { SITE_URL } from '../api';
import { THEMES, type Theme } from '../utils/theme';
import './Settings.css';

/** chrome.* only exists once this is loaded as an extension — under `vite dev`
 *  the popup is an ordinary page, so the version is simply unknown there. */
function extensionVersion(): string | null {
  type Runtime = { getManifest?: () => { version?: string } };
  const runtime = (globalThis as { chrome?: { runtime?: Runtime } }).chrome?.runtime;
  try {
    return runtime?.getManifest?.().version ?? null;
  } catch {
    return null;
  }
}

export default function Settings({
  theme,
  onTheme,
}: {
  theme: Theme;
  onTheme: (theme: Theme) => void;
}) {
  const version = extensionVersion();

  return (
    <div className="settings">
      <section>
        <h2 className="section-label">Appearance</h2>
        {/* radiogroup, not buttons: this is one choice out of three, and the
            arrow keys should move between them the way a radio group does. */}
        <div className="seg" role="radiogroup" aria-label="Theme">
          {THEMES.map(({ value, label }) => (
            <button
              key={value}
              className={value === theme ? 'seg-opt on' : 'seg-opt'}
              type="button"
              role="radio"
              aria-checked={value === theme}
              onClick={() => onTheme(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="muted seg-note">
          {theme === 'system'
            ? 'Follows your computer’s light or dark setting.'
            : `Always ${theme}, whatever your computer is set to.`}
        </p>
      </section>

      <section>
        <h2 className="section-label">About</h2>
        <dl className="about">
          <dt>Version</dt>
          <dd>{version ?? 'Development build'}</dd>
        </dl>
        <div className="about-links">
          <a className="btn secondary" href={SITE_URL} target="_blank" rel="noreferrer">
            Open RateMyHusky
          </a>
          <a className="btn secondary" href={`${SITE_URL}/faq`} target="_blank" rel="noreferrer">
            FAQ
          </a>
          <a className="btn secondary" href={`${SITE_URL}/privacy`} target="_blank" rel="noreferrer">
            Privacy
          </a>
        </div>
      </section>
    </div>
  );
}
