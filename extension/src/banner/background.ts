/// <reference types="vite/client" />
import { BANNER_MATCHES, BANNER_ORIGIN, MAX_CRNS, OPEN_KEY } from './messages';
import type {
  LookupRequest,
  LookupResponse,
  OpenRequest,
  SaveRequest,
  SaveResponse,
  Section,
} from './messages';
import { saveProfessorCourse, SLUG } from './saved';

const SCRIPT_ID = 'banner-ratings';
/** The fallback page is always the real site, even when VITE_RMH_API points
 *  the lookups at a local backend. Not imported from api.ts, which would pull
 *  the popup's fixtures into the worker. */
const SITE_URL = 'https://ratemyhusky.com';

/** Registers the content script at runtime instead of declaring it in the
 *  manifest.
 *
 *  A manifest `content_scripts` entry asks for its host permission at install
 *  time, so every user would be warned about nubanner.neu.edu whether or not
 *  they ever switch this on — the opposite of what optional_host_permissions
 *  is for. Registering here means the extension touches nothing but
 *  ratemyhusky.com until the Settings toggle grants the origin. */
export async function syncBannerScript(): Promise<void> {
  const granted = await chrome.permissions.contains({ origins: [BANNER_ORIGIN] });
  const existing = await chrome.scripting.getRegisteredContentScripts({ ids: [SCRIPT_ID] });

  if (granted && existing.length === 0) {
    await chrome.scripting.registerContentScripts([
      {
        id: SCRIPT_ID,
        matches: BANNER_MATCHES,
        js: ['content.js'],
        runAt: 'document_idle',
      },
    ]);
  } else if (!granted && existing.length > 0) {
    await chrome.scripting.unregisterContentScripts({ ids: [SCRIPT_ID] });
  }
}

// A registration survives a browser restart, so onStartup isn't what puts it
// there — it's what removes it if the permission was revoked from Chrome's
// own settings page while the browser was closed, which fires no event.
chrome.runtime.onInstalled.addListener(() => void syncBannerScript());
chrome.runtime.onStartup.addListener(() => void syncBannerScript());
chrome.permissions.onAdded.addListener(() => void syncBannerScript());
chrome.permissions.onRemoved.addListener(() => void syncBannerScript());

/** Over the site, never the Railway host: only traffic proxied through the
 *  site carries PROXY_SECRET. `VITE_RMH_API=http://localhost:5001 npm run build`
 *  points it at a local backend instead, which also needs that origin in the
 *  manifest's host_permissions. */
const API_URL = `${import.meta.env.VITE_RMH_API ?? 'https://ratemyhusky.com'}/api/banner/sections`;
const TIMEOUT_MS = 10_000;

/** Asks the endpoint about one page of CRNs and returns its rows keyed by CRN.
 *  The endpoint 400s anything malformed or over MAX_CRNS, so the same checks
 *  run here first rather than spending a request on an answer we know. */
async function lookupSections({ term, crns }: LookupRequest): Promise<LookupResponse> {
  if (!/^\d{6}$/.test(term)) return { ok: false, message: 'Invalid term' };
  if (
    !Array.isArray(crns) ||
    crns.length === 0 ||
    crns.length > MAX_CRNS ||
    crns.some((crn) => typeof crn !== 'string' || !/^\d{1,10}$/.test(crn))
  ) {
    return { ok: false, message: 'Invalid CRNs' };
  }

  const params = new URLSearchParams({ term, crns: [...new Set(crns)].join(',') });
  // A worker that never hears back would leave the content script's request
  // open, and its CRNs marked as asking, until the page is reloaded.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch(`${API_URL}?${params}`, {
      credentials: 'omit',
      signal: controller.signal,
    });
    if (!response.ok) return { ok: false, message: `Rating lookup failed: ${response.status}` };
    return { ok: true, sections: (await response.json()) as Record<string, Section> };
  } catch (err) {
    return { ok: false, message: err instanceof Error ? err.message : 'Lookup failed' };
  } finally {
    clearTimeout(timeout);
  }
}


/** Opens the popup on the professor a Banner badge was clicked for. The popup
 *  reads the slug from session storage as it starts, so it's written first.
 *  openPopup fails where Chrome won't allow it — older than 127, or the
 *  window isn't focused — and the professor's page on the site opens in a
 *  new tab instead, so the click always goes somewhere. */
async function openFromBanner(slug: string, windowId: number | undefined): Promise<void> {
  try {
    await chrome.storage.session.set({ [OPEN_KEY]: slug });
    await chrome.action.openPopup(windowId != null ? { windowId } : undefined);
  } catch (err) {
    // Logged because the fallback looks exactly like the old link working.
    console.warn('[RateMyHusky] popup did not open, using the site instead:', err);
    await chrome.storage.session.remove(OPEN_KEY).catch(() => {});
    await chrome.tabs.create({ url: `${SITE_URL}/professors/${encodeURIComponent(slug)}` });
  }
}

chrome.runtime.onMessage.addListener(
  (message: LookupRequest | SaveRequest | OpenRequest, sender, sendResponse) => {
    if (
      message?.type !== 'banner:lookup' &&
      message?.type !== 'banner:save' &&
      message?.type !== 'banner:open'
    ) {
      return false;
    }

    if (sender.id !== chrome.runtime.id) {
      sendResponse({ ok: false, message: 'Unauthorized sender' });
      return false;
    }

    if (message.type === 'banner:lookup') {
      void lookupSections(message).then(sendResponse);
      return true;
    }

    // only the Banner content script can save entries or open the popup
    const origin = sender.url ? new URL(sender.url).origin : '';

    if (message.type === 'banner:open') {
      // The slug ends up in a URL on the fallback path, so it's checked here
      // rather than trusted from the page's side of the message.
      if (origin === 'https://nubanner.neu.edu' && SLUG.test(message.slug)) {
        void openFromBanner(message.slug, sender.tab?.windowId);
      }
      return false;
    }

    if (origin !== 'https://nubanner.neu.edu') {
      sendResponse({
        ok: false,
        message: 'Only Banner can save professors',
      } satisfies SaveResponse);

      return false;
    }

    void saveProfessorCourse(message.entry)
      .then(() => sendResponse({ ok: true } satisfies SaveResponse))
      .catch(() =>
        sendResponse({
          ok: false,
          message: 'Could not save professor',
        } satisfies SaveResponse)
      );

    // keep the message channel open for the async storage operation
    return true;
  }
);
