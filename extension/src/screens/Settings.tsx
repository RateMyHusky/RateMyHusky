import { useEffect, useState } from 'react';
import { SITE_URL } from '../api';
import { hasBannerAccess, requestBannerAccess, revokeBannerAccess } from '../banner/permission';
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
  const [bannerAccess, setBannerAccess] = useState(false);
  const [permissionError, setPermissionError] = useState('');
  const [changing, setChanging] = useState(false);
  useEffect(() => {
    if (typeof chrome === 'undefined' || !chrome.permissions) return;
    void hasBannerAccess().then(setBannerAccess).catch(() => setPermissionError('Unable to read permission'));
  }, []);

  async function toggleBanner(): Promise<void> {
    setChanging(true);
    setPermissionError('');
    try {
      const changed = bannerAccess ? await revokeBannerAccess() : await requestBannerAccess();
      if (changed) setBannerAccess(!bannerAccess);
    } catch {
      setPermissionError('Unable to update Banner permission');
    } finally {
      setChanging(false);
    }
  }

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
        <h2 className="section-label">Banner integration</h2>
        <label className="banner-toggle">
          <span>Show RateMyHusky ratings on Banner</span>
          <input type="checkbox" checked={bannerAccess} disabled={changing || typeof chrome === 'undefined'}
            onChange={() => void toggleBanner()} />
        </label>
        <p className="muted seg-note">Optional. Reads classes already shown in Banner; never requests Banner data.</p>
        {permissionError && <p role="alert" className="muted">{permissionError}</p>}
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
