import { BANNER_MATCHES, BANNER_ORIGIN } from './messages';
import type { LookupRequest, LookupResponse } from './messages';

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

/** Step 4 fills this in: GET /api/banner/sections over the site (never the
 *  Railway host — only traffic proxied through the site carries PROXY_SECRET),
 *  with credentials: 'omit', and return the rows keyed by CRN. */
async function lookupSections(_request: LookupRequest): Promise<LookupResponse> {
  return { ok: false, message: 'Not implemented yet.' };
}

chrome.runtime.onMessage.addListener((message: LookupRequest, _sender, sendResponse) => {
  if (message?.type !== 'banner:lookup') return false;
  // Returning true is what keeps the channel open for an async reply. Without
  // it the port closes as this listener returns and the content script's
  // sendMessage resolves undefined — with no error on either side.
  lookupSections(message).then(sendResponse);
  return true;
});
