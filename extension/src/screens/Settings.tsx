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
        {/* Real radios rather than buttons wearing role="radio": arrow-key
            movement, the single tab stop and the "radio, 1 of 3" announcement
            all come from the browser. Styling them as a segmented control is
            a label away; re-implementing the keyboard model isn't. */}
        <div className="seg" role="radiogroup" aria-label="Theme">
          {THEMES.map(({ value, label }) => (
            <label key={value} className={value === theme ? 'seg-opt on' : 'seg-opt'}>
              <input
                type="radio"
                name="theme"
                value={value}
                checked={value === theme}
                onChange={() => onTheme(value)}
              />
              {label}
            </label>
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
