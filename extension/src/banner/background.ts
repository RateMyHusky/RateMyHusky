import { BANNER_MATCHES, BANNER_ORIGIN, MAX_CRNS } from './messages';
import type { LookupRequest, LookupResponse, Section } from './messages';

const SCRIPT_ID = 'banner-ratings';

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
 *  site carries PROXY_SECRET. */
const API_URL = 'https://ratemyhusky.com/api/banner/sections';
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

chrome.runtime.onMessage.addListener((message: LookupRequest, sender, sendResponse) => {
  if (message?.type !== 'banner:lookup') return false;
  // onMessage only hears from this extension's own scripts (others arrive on
  // onMessageExternal), so this never fires today. It's cheap insurance.
  if (sender.id !== chrome.runtime.id) {
    sendResponse({ ok: false, message: 'Unauthorized sender' });
    return false;
  }
  // Returning true is what keeps the channel open for an async reply. Without
  // it the port closes as this listener returns and the content script's
  // sendMessage resolves undefined — with no error on either side.
  lookupSections(message).then(sendResponse);
  return true;
});
