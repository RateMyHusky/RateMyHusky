/// <reference types="vite/client" />
import { BANNER_MATCHES, BANNER_ORIGIN, MAX_CRNS, OPEN_KEY } from './messages';
import type { LookupRequest, LookupResponse, OpenRequest, Section } from './messages';
import { SLUG } from '../utils/saved';

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
chrome.permissions.onAdded.addListener((added) => {
  void syncBannerScript().then(() => {
    if (added.origins?.includes(BANNER_ORIGIN)) void injectIntoOpenTabs();
  });
});
chrome.permissions.onRemoved.addListener(() => void syncBannerScript());

/** A registered content script only runs on pages loaded after it was
 *  registered. Without this, a student with Plan Ahead already open turns the
 *  setting on, goes back to the tab, and finds nothing — the feature looks
 *  broken until they think to reload. content.ts stands down if it's already
 *  running, so a tab that somehow has it gets no second copy. */
async function injectIntoOpenTabs(): Promise<void> {
  const tabs = await chrome.tabs.query({ url: BANNER_MATCHES });
  await Promise.all(
    tabs.map((tab) =>
      tab.id == null
        ? undefined
        : chrome.scripting
            .executeScript({ target: { tabId: tab.id }, files: ['content.js'] })
            // A tab mid-navigation or showing an error page refuses; the
            // registered script covers it on its next load.
            .catch(() => undefined),
    ),
  );
}

const bannerGranted = () => chrome.permissions.contains({ origins: [BANNER_ORIGIN] });

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
  // Switching the setting off unregisters the script for future page loads,
  // but a Banner tab that's already open keeps the copy it has. Checked on
  // every lookup, so "turn this off at any time" (Privacy §9) holds for those
  // tabs too: nothing more leaves the browser, and the tab clears its badges.
  if (!(await bannerGranted())) {
    return { ok: false, message: 'Banner access is off', retry: false, disabled: true };
  }
  if (!/^\d{6}$/.test(term)) return { ok: false, message: 'Invalid term', retry: false };
  if (
    !Array.isArray(crns) ||
    crns.length === 0 ||
    crns.length > MAX_CRNS ||
    crns.some((crn) => typeof crn !== 'string' || !/^\d{1,10}$/.test(crn))
  ) {
    return { ok: false, message: 'Invalid CRNs', retry: false };
  }

  // A worker that never hears back would leave the content script's request
  // open, and its CRNs marked as asking, until the page is reloaded.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    // POST, not a query string: request logs keep URLs, and a URL listing
    // the CRNs on someone's screen is a record of what they were looking at.
    const response = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ term, crns: [...new Set(crns)] }),
      credentials: 'omit',
      signal: controller.signal,
    });
    if (!response.ok) {
      return {
        ok: false,
        message: `Rating lookup failed: ${response.status}`,
        // Rate limited or the server's having a moment: ask again later. A
        // 4xx otherwise is about the request, and repeating it won't help.
        retry: response.status === 429 || response.status >= 500,
      };
    }
    return { ok: true, sections: (await response.json()) as Record<string, Section> };
  } catch (err) {
    // Timed out or the connection dropped.
    return { ok: false, message: err instanceof Error ? err.message : 'Lookup failed', retry: true };
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
    // Dev builds only: the fallback looks exactly like the old link working.
    if (import.meta.env.DEV) console.warn('[RateMyHusky] popup did not open:', err);
    await chrome.storage.session.remove(OPEN_KEY).catch(() => {});
    await chrome.tabs.create({ url: `${SITE_URL}/professors/${encodeURIComponent(slug)}` });
  }
}

chrome.runtime.onMessage.addListener(
  (message: LookupRequest | OpenRequest, sender, sendResponse) => {
    if (message?.type !== 'banner:lookup' && message?.type !== 'banner:open') return false;

    // onMessage only hears from this extension's own scripts (others arrive on
    // onMessageExternal), so this never fires today. It's cheap insurance.
    if (sender.id !== chrome.runtime.id) {
      sendResponse({ ok: false, message: 'Unauthorized sender' });
      return false;
    }

    if (message.type === 'banner:lookup') {
      // Returning true is what keeps the channel open for an async reply.
      void lookupSections(message).then(sendResponse);
      return true;
    }

    // Only the Banner content script opens the popup, and the slug ends up in
    // a URL on the fallback path, so it's checked rather than trusted.
    const origin = sender.url ? new URL(sender.url).origin : '';
    if (origin === 'https://nubanner.neu.edu' && SLUG.test(message.slug)) {
      void openFromBanner(message.slug, sender.tab?.windowId);
    }
    return false;
  },
);
