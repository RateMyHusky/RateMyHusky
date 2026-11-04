import { BANNER_ORIGIN } from './messages';

/** What the Settings toggle reads and flips (step 5). Granting the origin is
 *  the whole switch: the worker's permission listeners register the content
 *  script when it's added and unregister it when it's removed, so the toggle
 *  never touches chrome.scripting itself. */
const banner: chrome.permissions.Permissions = { origins: [BANNER_ORIGIN] };

export function hasBannerAccess(): Promise<boolean> {
  return chrome.permissions.contains(banner);
}

/** Call it straight from the toggle's change handler. Chrome refuses a
 *  permission request that no user gesture led to, and opens its own prompt
 *  for the one it allows. Resolves false if the student declines. */
export function requestBannerAccess(): Promise<boolean> {
  return chrome.permissions.request(banner);
}

export function revokeBannerAccess(): Promise<boolean> {
  return chrome.permissions.remove(banner);
}
