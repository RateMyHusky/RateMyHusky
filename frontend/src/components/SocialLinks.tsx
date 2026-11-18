import { useEffect, useState } from 'react';
import './FloatingButton.css';
import './SocialLinks.css';

const INSTAGRAM_URL = 'https://www.instagram.com/ratemyhusky/';
const CHROME_EXTENSION_URL = 'https://chromewebstore.google.com/detail/ratemyhusky/mclablclbfgbkhnhjmojmofhomllgkja';

type UAData = { brands?: { brand: string }[]; mobile?: boolean };

/** Desktop Chromium (Chrome, Edge, Brave, Opera, Arc...) is what can install from
 *  the Chrome Web Store; Safari, Firefox and every phone browser can't. */
function canInstallChromeExtension(): boolean {
  if (typeof navigator === 'undefined') return false;
  const uaData = (navigator as Navigator & { userAgentData?: UAData }).userAgentData;
  if (uaData?.brands) {
    return !uaData.mobile && uaData.brands.some(b => /Chromium/i.test(b.brand));
  }
  const ua = navigator.userAgent;
  return /(Chrome|Chromium|Edg)\//.test(ua) && !/Mobi|Android|CriOS|EdgiOS/.test(ua);
}

const InstagramIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
    <rect x="2.5" y="2.5" width="19" height="19" rx="5.5" fill="none" stroke="currentColor" strokeWidth="2" />
    <circle cx="12" cy="12" r="4.3" fill="none" stroke="currentColor" strokeWidth="2" />
    <circle cx="17.4" cy="6.6" r="1.3" fill="currentColor" />
  </svg>
);

const ChromeIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
    <path d="M12 12 L2.47 6.5 A11 11 0 0 1 21.53 6.5 Z" fill="#DB4437" />
    <path d="M12 12 L21.53 6.5 A11 11 0 0 1 12 23 Z" fill="#F4B400" />
    <path d="M12 12 L12 23 A11 11 0 0 1 2.47 6.5 Z" fill="#0F9D58" />
    <circle cx="12" cy="12" r="5.2" fill="#fff" />
    <circle cx="12" cy="12" r="4" fill="#4285F4" />
  </svg>
);

/** The Instagram link, plus "Add to Chrome" where the extension can be installed.
 *  `buttonClass` is added to each link: "floating-btn" for the corner buttons. */
export const SocialLinkList = ({ buttonClass = '' }: { buttonClass?: string }) => {
  const showChrome = canInstallChromeExtension();
  return (
    <>
      <a
        href={INSTAGRAM_URL}
        className={`social-link social-link-instagram ${buttonClass}`}
        target="_blank"
        rel="noopener noreferrer"
        aria-label="RateMyHusky on Instagram"
        title="Follow us on Instagram"
      >
        <InstagramIcon />
      </a>
      {showChrome && (
        <a
          href={CHROME_EXTENSION_URL}
          className={`social-link social-link-chrome ${buttonClass}`}
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Add the RateMyHusky extension to Chrome"
        >
          <ChromeIcon />
          <span>Add to Chrome</span>
        </a>
      )}
    </>
  );
};

/** Homepage only: the same links pinned to the bottom-left corner on desktop,
 *  mirroring the theme toggle. They fade out once the footer (which carries the
 *  same links) scrolls into view, so they never cover it or show twice. */
const SocialLinks = () => {
  const [footerInView, setFooterInView] = useState(false);

  useEffect(() => {
    const footer = document.querySelector('footer.footer');
    if (!footer || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(([entry]) => setFooterInView(entry.isIntersecting));
    observer.observe(footer);
    return () => observer.disconnect();
  }, []);

  return (
    <nav
      className={`floating-corner social-links${footerInView ? ' social-links-hidden' : ''}`}
      aria-label="RateMyHusky on Instagram and Chrome"
      aria-hidden={footerInView || undefined}
    >
      <SocialLinkList buttonClass="floating-btn" />
    </nav>
  );
};

export default SocialLinks;
